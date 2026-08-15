"""KitJob endpoints (kitting / bagging lifecycle)."""

from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, touch, parse_iso
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_int, as_str_list,
    as_dt, pagination_params, paginate,
)
from response import success, success_list
from services import kit_packaging_cost, STATION_BUFFER_MINUTES

bp = Blueprint("kitjobs", __name__)

READ_ROLES = ["DistributorAdmin", "WarehouseOperator"]
NON_TERMINAL = ("DRAFT", "PICKING", "ON_HOLD", "PACKED")


def serialize(j):
    return {
        "id": j["id"],
        "site_id": j["site_id"],
        "kit_name": j["kit_name"],
        "component_part_ids": j["component_part_ids"],
        "qty_per_part": j["qty_per_part"],
        "kit_count": j["kit_count"],
        "station_window_start": j["station_window_start"],
        "station_window_end": j["station_window_end"],
        "packaging_cost_cents": j["packaging_cost_cents"],
        "status": j["status"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def _load_job(jid):
    job = store.kitjobs.get(jid)
    if job is None:
        raise errors.not_found("kit job not found")
    return job


def _release_reservations(job):
    """Compensating release: reserved back into available for each component."""
    qty = job["qty_per_part"] * job["kit_count"]
    for pid in job["component_part_ids"]:
        part = store.parts[pid]
        part["reserved_qty"] -= qty
        part["available_qty"] += qty
        touch(part)


@bp.post("/vmi/kit-jobs")
def create_kit_job():
    role = authenticate()
    body = json_body()
    site_id = as_str(need(body, "site_id"), "site_id")
    kit_name = as_str(need(body, "kit_name"), "kit_name")
    component_part_ids = as_str_list(
        need(body, "component_part_ids"), "component_part_ids"
    )
    qty_per_part = as_int(need(body, "qty_per_part"), "qty_per_part")
    kit_count = as_int(need(body, "kit_count"), "kit_count")
    station_window_start = as_dt(
        need(body, "station_window_start"), "station_window_start"
    )
    station_window_end = as_dt(
        need(body, "station_window_end"), "station_window_end"
    )
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        # existence, left-to-right: site, then component parts in order
        if site_id not in store.sites:
            raise errors.not_found("site not found")
        for pid in component_part_ids:
            if pid not in store.parts:
                raise errors.not_found("component part not found: %s" % pid)
        # stage 10: closed-interval-with-buffer station-window semantics
        nws = parse_iso(station_window_start)
        nwe = parse_iso(station_window_end)
        buffer = timedelta(minutes=STATION_BUFFER_MINUTES)
        if not nws < nwe:
            raise errors.station_conflict(
                "station_window_start must be strictly before station_window_end"
            )
        for other in store.kitjobs.values():
            if other["status"] not in NON_TERMINAL:
                continue
            ows = parse_iso(other["station_window_start"])
            owe = parse_iso(other["station_window_end"])
            if nws < owe + buffer and ows <= nwe:
                raise errors.station_conflict(
                    "station window collides with an existing non-terminal job"
                )
        # stage 12: component list bounds and part liveness
        if not (1 <= len(component_part_ids) <= 20):
            raise errors.quantity_bounds(
                "component_part_ids must hold between 1 and 20 elements"
            )
        if len(set(component_part_ids)) != len(component_part_ids):
            raise errors.quantity_bounds("component_part_ids must not contain duplicates")
        for pid in component_part_ids:
            if store.parts[pid]["status"] != "ACTIVE":
                raise errors.quantity_bounds(
                    "every kit component part must be ACTIVE"
                )
        if qty_per_part < 1:
            raise errors.quantity_bounds("qty_per_part must be >= 1")
        if kit_count < 1:
            raise errors.quantity_bounds("kit_count must be >= 1")
        ts = now_iso()
        job = {
            "id": new_id(),
            "site_id": site_id,
            "kit_name": kit_name,
            "component_part_ids": list(component_part_ids),
            "qty_per_part": qty_per_part,
            "kit_count": kit_count,
            "station_window_start": station_window_start,
            "station_window_end": station_window_end,
            "packaging_cost_cents": None,
            "status": "DRAFT",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.kitjobs[job["id"]] = job
        return success(serialize(job), 201)


@bp.get("/vmi/kit-jobs/<jid>")
def get_kit_job(jid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    return success(serialize(_load_job(jid)), 200)


@bp.get("/vmi/kit-jobs")
def list_kit_jobs():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = sorted(store.kitjobs.values(), key=lambda j: j["_seq"])
    if site_id is not None:
        items = [j for j in items if j["site_id"] == site_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(j) for j in page], total, limit, offset)


@bp.post("/vmi/kit-jobs/<jid>/start-picking")
def start_picking(jid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        job = _load_job(jid)
        if job["status"] != "DRAFT":
            raise errors.invalid_state("kit job is not DRAFT")
        # stage 12: every component still ACTIVE
        for pid in job["component_part_ids"]:
            if store.parts[pid]["status"] != "ACTIVE":
                raise errors.quantity_bounds(
                    "every kit component part must be ACTIVE"
                )
        # stage 13: stock sufficiency — check ALL before committing ANY
        qty = job["qty_per_part"] * job["kit_count"]
        for pid in job["component_part_ids"]:
            if store.parts[pid]["available_qty"] < qty:
                raise errors.insufficient_stock(
                    "component part %s has insufficient available stock" % pid
                )
        job["status"] = "PICKING"
        touch(job)
        for pid in job["component_part_ids"]:
            part = store.parts[pid]
            part["reserved_qty"] += qty
            part["available_qty"] -= qty
            touch(part)
        return success(serialize(job), 200)


@bp.post("/vmi/kit-jobs/<jid>/hold")
def hold_job(jid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        job = _load_job(jid)
        if job["status"] != "PICKING":
            raise errors.invalid_state("kit job is not PICKING")
        job["status"] = "ON_HOLD"
        touch(job)  # reservations retained while ON_HOLD
        return success(serialize(job), 200)


@bp.post("/vmi/kit-jobs/<jid>/resume")
def resume_job(jid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        job = _load_job(jid)
        if job["status"] != "ON_HOLD":
            raise errors.invalid_state("kit job is not ON_HOLD")
        # re-verify every component is still ACTIVE
        for pid in job["component_part_ids"]:
            if store.parts[pid]["status"] != "ACTIVE":
                raise errors.quantity_bounds(
                    "every kit component part must be ACTIVE"
                )
        job["status"] = "PICKING"
        touch(job)
        return success(serialize(job), 200)


@bp.post("/vmi/kit-jobs/<jid>/pack")
def pack_job(jid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        job = _load_job(jid)
        if job["status"] != "PICKING":
            raise errors.invalid_state("kit job is not PICKING")
        job["packaging_cost_cents"] = kit_packaging_cost(job)
        job["status"] = "PACKED"
        touch(job)
        return success(serialize(job), 200)


@bp.post("/vmi/kit-jobs/<jid>/complete")
def complete_job(jid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        job = _load_job(jid)
        if job["status"] != "PACKED":
            raise errors.invalid_state("kit job is not PACKED")
        job["status"] = "COMPLETED"
        touch(job)
        qty = job["qty_per_part"] * job["kit_count"]
        for pid in job["component_part_ids"]:
            part = store.parts[pid]
            # reserved stock leaves the building; available unchanged
            part["reserved_qty"] -= qty
            part["total_stock_qty"] -= qty
            touch(part)
        return success(serialize(job), 200)


@bp.post("/vmi/kit-jobs/<jid>/scrap")
def scrap_job(jid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["WarehouseOperator"])
    with store.lock:
        job = _load_job(jid)
        source = job["status"]
        if source not in ("DRAFT", "PICKING", "ON_HOLD"):
            raise errors.invalid_state(
                "kit job cannot be scrapped from its current state"
            )
        job["status"] = "SCRAPPED"
        touch(job)
        if source in ("PICKING", "ON_HOLD"):
            _release_reservations(job)
        return success(serialize(job), 200)
