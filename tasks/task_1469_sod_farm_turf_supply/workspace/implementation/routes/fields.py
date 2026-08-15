"""Fields: inventory, quality updates, maturity scan, archive, re-seed plans."""
from flask import Blueprint, request

import calc
import db
import services
from auth import require_roles
from db import common_fields
from errors import (err, ERR_ALREADY_TERMINAL, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_RESEED_NOT_ALLOWED,
                    ERR_SEED_SHORTFALL)
from serialize import pub_field, pub_reseed_plan
from util import (as_int, as_num, as_str, body, ok, ok_list, paged, pagination,
                  parse_dt, require, sort_created)

bp = Blueprint("fields", __name__)

_ACTIVE_ORDER_STATES = {"PLACED", "CONFIRMED", "OUT_FOR_DELIVERY", "DELIVERED",
                        "INSTALLING", "INSTALLED"}


def _get_field(fid):
    field = db.store.fields.get(fid)
    if field is None:
        raise err(ERR_NOT_FOUND, f"field {fid} not found")
    return field


@bp.route("/fields", methods=["POST"])
def create_field():
    require_roles("FarmManager")
    payload = body()
    name = as_str(require(payload, "name"), "name")
    variety_id = as_str(require(payload, "variety_id"), "variety_id")
    variety = db.store.variety_configs.get(variety_id)
    if variety is None:
        raise err(ERR_NOT_FOUND, f"variety {variety_id} not found")
    field_sqft = as_num(require(payload, "field_sqft"), "field_sqft", minimum=0,
                        exclusive_minimum=True)
    last_planted_at = parse_dt(require(payload, "last_planted_at"), "last_planted_at")
    mow_count = as_int(require(payload, "mow_count"), "mow_count", minimum=0)
    last_mowed_at = parse_dt(require(payload, "last_mowed_at"), "last_mowed_at")
    soil = as_num(require(payload, "soil_moisture_pct"), "soil_moisture_pct", 0, 100)
    health = as_num(require(payload, "health_score"), "health_score", 0, 100)
    field = common_fields()
    field.update({
        "name": name,
        "variety_id": variety_id,
        "field_sqft": field_sqft,
        "last_planted_at": last_planted_at,
        "mow_count": mow_count,
        "last_mowed_at": last_mowed_at,
        "soil_moisture_pct": soil,
        "health_score": health,
        "remaining_sqft": field_sqft,
        "status": "ACTIVE",
    })
    _, maturity = calc.compute_maturity(field)
    field["maturity_state"] = maturity
    db.store.fields[field["id"]] = field
    return ok(pub_field(field), 201)


@bp.route("/fields", methods=["GET"])
def list_fields():
    require_roles("FarmManager", "SalesRep", "HarvestSupervisor")
    limit, offset = pagination()
    variety_id = request.args.get("variety_id")
    maturity_filter = request.args.get("maturity_state")
    status_filter = request.args.get("status")
    items = sort_created(db.store.fields.values())
    if variety_id is not None:
        items = [f for f in items if f["variety_id"] == variety_id]
    if maturity_filter is not None:
        items = [f for f in items if calc.compute_maturity(f)[1] == maturity_filter]
    if status_filter is not None:
        items = [f for f in items if f["status"] == status_filter]
    else:
        # archived fields are hidden unless explicitly requested
        items = [f for f in items if f["status"] != "ARCHIVED"]
    page, total = paged(items, limit, offset)
    return ok_list([pub_field(f) for f in page], total, limit, offset)


@bp.route("/fields/<fid>", methods=["GET"])
def get_field(fid):
    require_roles("FarmManager", "SalesRep", "HarvestSupervisor")
    return ok(pub_field(_get_field(fid)), 200)


@bp.route("/fields/<fid>/quality", methods=["PATCH"])
def update_quality(fid):
    require_roles("FarmManager")
    field = _get_field(fid)
    payload = body()
    updates = {}
    if "mow_count" in payload and payload["mow_count"] is not None:
        updates["mow_count"] = as_int(payload["mow_count"], "mow_count", minimum=0)
    if "last_mowed_at" in payload and payload["last_mowed_at"] is not None:
        updates["last_mowed_at"] = parse_dt(payload["last_mowed_at"], "last_mowed_at")
    if "soil_moisture_pct" in payload and payload["soil_moisture_pct"] is not None:
        updates["soil_moisture_pct"] = as_num(payload["soil_moisture_pct"], "soil_moisture_pct", 0, 100)
    if "health_score" in payload and payload["health_score"] is not None:
        updates["health_score"] = as_num(payload["health_score"], "health_score", 0, 100)
    if field["status"] == "ARCHIVED":
        raise err(ERR_ALREADY_TERMINAL, f"field {fid} is archived")
    field.update(updates)
    db.bump(field)
    return ok(pub_field(field), 200)


@bp.route("/fields/<fid>/maturity-scan", methods=["POST"])
def maturity_scan(fid):
    require_roles("FarmManager")
    field = _get_field(fid)
    if field["status"] == "ARCHIVED":
        raise err(ERR_ALREADY_TERMINAL, f"field {fid} is archived")
    services.maturity_scan(field)
    return ok(pub_field(field), 200)


@bp.route("/fields/<fid>/archive", methods=["POST"])
def archive_field(fid):
    require_roles("FarmManager")
    field = _get_field(fid)
    if field["status"] == "ARCHIVED":
        raise err(ERR_ALREADY_TERMINAL, f"field {fid} is already archived")
    for b in db.store.harvest_batches.values():
        if b["field_id"] == fid and b["status"] in ("PENDING", "COMPLETE"):
            raise err(ERR_INVALID_STATE, "field has live harvest batches")
    for p in db.store.reseed_plans.values():
        if p["field_id"] == fid and p["status"] in ("PLANNING", "IN_PROGRESS"):
            raise err(ERR_INVALID_STATE, "field has an active re-seed plan")
    field["status"] = "ARCHIVED"
    db.bump(field)
    return ok(pub_field(field), 200)


# ------------------------------------------------------------------ re-seed
@bp.route("/fields/<fid>/reseed-plans", methods=["POST"])
def create_reseed_plan(fid):
    require_roles("FarmManager")
    field = _get_field(fid)
    payload = body()
    planned_date = parse_dt(require(payload, "planned_date"), "planned_date")
    if field["status"] == "ARCHIVED":
        raise err(ERR_ALREADY_TERMINAL, f"field {fid} is archived")
    _, maturity = calc.compute_maturity(field)
    if maturity not in ("MATURE", "OVERAGED"):
        raise err(ERR_RESEED_NOT_ALLOWED,
                  f"field maturity is {maturity}; re-seeding requires MATURE or OVERAGED")
    for b in db.store.harvest_batches.values():
        if b["field_id"] == fid and b["order_id"] is not None:
            order = db.store.orders.get(b["order_id"])
            if order is not None and order["status"] in _ACTIVE_ORDER_STATES:
                raise err(ERR_RESEED_NOT_ALLOWED,
                          "field has batches linked to a non-terminal order")
    for p in db.store.reseed_plans.values():
        if p["field_id"] == fid and p["status"] in ("PLANNING", "IN_PROGRESS"):
            raise err(ERR_RESEED_NOT_ALLOWED, "field already has an active re-seed plan")
    variety = db.store.variety_configs.get(field["variety_id"])
    plan = common_fields()
    plan.update({
        "field_id": fid,
        "planned_date": planned_date,
        "target_seed_lbs": calc.target_seed_lbs(field, variety),
        "actual_seed_lbs": None,
        "status": "PLANNING",
        "completed_at": None,
    })
    db.store.reseed_plans[plan["id"]] = plan
    return ok(pub_reseed_plan(plan), 201)


@bp.route("/fields/<fid>/reseed-plans", methods=["GET"])
def list_reseed_plans(fid):
    require_roles("FarmManager")
    _get_field(fid)
    limit, offset = pagination()
    items = sort_created(p for p in db.store.reseed_plans.values() if p["field_id"] == fid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_reseed_plan(p) for p in page], total, limit, offset)


def _get_plan(pid):
    plan = db.store.reseed_plans.get(pid)
    if plan is None:
        raise err(ERR_NOT_FOUND, f"re-seed plan {pid} not found")
    return plan


@bp.route("/reseed-plans/<pid>/start", methods=["POST"])
def start_reseed_plan(pid):
    require_roles("FarmManager")
    plan = _get_plan(pid)
    if plan["status"] == "COMPLETED":
        raise err(ERR_ALREADY_TERMINAL, f"re-seed plan {pid} is completed")
    if plan["status"] != "PLANNING":
        raise err(ERR_INVALID_STATE, f"re-seed plan {pid} is not in PLANNING")
    plan["status"] = "IN_PROGRESS"
    db.bump(plan)
    return ok(pub_reseed_plan(plan), 200)


@bp.route("/reseed-plans/<pid>/complete", methods=["POST"])
def complete_reseed_plan(pid):
    require_roles("FarmManager")
    plan = _get_plan(pid)
    payload = body()
    actual = as_num(require(payload, "actual_seed_lbs"), "actual_seed_lbs", minimum=0)
    if plan["status"] == "COMPLETED":
        raise err(ERR_ALREADY_TERMINAL, f"re-seed plan {pid} is completed")
    if plan["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE, f"re-seed plan {pid} is not in IN_PROGRESS")
    if actual < plan["target_seed_lbs"]:
        raise err(ERR_SEED_SHORTFALL,
                  f"actual_seed_lbs {actual} below target {plan['target_seed_lbs']}")
    plan["status"] = "COMPLETED"
    plan["actual_seed_lbs"] = actual
    plan["completed_at"] = db.now()
    db.bump(plan)
    field = db.store.fields.get(plan["field_id"])
    if field is not None:
        services.reseed_complete_cascade(field)
    return ok(pub_reseed_plan(plan), 200)
