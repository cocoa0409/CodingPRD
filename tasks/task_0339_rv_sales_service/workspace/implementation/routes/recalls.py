"""Recall campaign + remedy routes (PRD 3.11)."""

from flask import Blueprint, request

import db
import errors
from common import (body, new_entity, touch, require_str, require_int, require_enum,
                    CLASS_TYPES, paginate, get_or_404, find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list
from services import recompute_open_recall_count

bp = Blueprint("recalls", __name__)

SEVERITIES = {"STOP_SALE", "ADVISORY"}


@bp.post("/recall-campaigns")
def create_campaign():
    _, role = get_auth()
    require_role(role, {"DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    code = require_str(data, "campaign_code")
    target_class = require_enum(data, "target_class_type", CLASS_TYPES)
    target_year = require_int(data, "target_model_year")
    severity = require_enum(data, "severity", SEVERITIES)

    for c in db.store["recall_campaigns"].values():
        if c["dealership_id"] == did and c["campaign_code"] == code:
            errors.err("ERR_DUPLICATE_CAMPAIGN", "campaign_code already used in this dealership.")

    rec = new_entity({
        "dealership_id": did,
        "campaign_code": code,
        "target_class_type": target_class,
        "target_model_year": target_year,
        "severity": severity,
        "status": "OPEN",
    })
    db.store["recall_campaigns"][rec["id"]] = rec

    # Side effect: create PENDING remedies for each in-scope unit; bump counts.
    for unit in db.store["units"].values():
        if (unit["dealership_id"] == did
                and unit["class_type"] == target_class
                and unit["model_year"] == target_year):
            remedy = new_entity({
                "dealership_id": did,
                "recall_campaign_id": rec["id"],
                "unit_id": unit["id"],
                "status": "PENDING",
            })
            db.store["recall_remedies"][remedy["id"]] = remedy
            recompute_open_recall_count(unit)
            touch(unit)

    return created(rec)


@bp.get("/recall-campaigns")
def list_campaigns():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    items = list(db.store["recall_campaigns"].values())
    a = request.args
    for field in ("dealership_id", "status", "target_class_type"):
        val = a.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/recall-campaigns/<rc_id>")
def get_campaign(rc_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    rec = get_or_404("recall_campaigns", rc_id)
    return ok(rec)


@bp.post("/recall-campaigns/<rc_id>/close")
def close_campaign(rc_id):
    _, role = get_auth()
    require_role(role, {"DealerManager"})
    campaign = get_or_404("recall_campaigns", rc_id)
    if campaign["status"] != "OPEN":
        errors.err("ERR_RECALL_BAD_STATE", "Campaign is not OPEN.")
    remedies = [r for r in db.store["recall_remedies"].values()
                if r["recall_campaign_id"] == rc_id]
    if any(r["status"] != "CLEARED" for r in remedies):
        errors.err("ERR_REMEDIES_OUTSTANDING", "Outstanding remedies block the close.")
    campaign["status"] = "CLOSED"
    touch(campaign)
    # Recompute open_recall_count for each targeted unit.
    targeted_unit_ids = {r["unit_id"] for r in remedies}
    for uid in targeted_unit_ids:
        unit = db.store["units"].get(uid)
        if unit:
            recompute_open_recall_count(unit)
            touch(unit)
    return ok(campaign)


@bp.get("/recall-remedies")
def list_remedies():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    items = list(db.store["recall_remedies"].values())
    a = request.args
    for field in ("recall_campaign_id", "unit_id", "status", "dealership_id"):
        val = a.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/recall-remedies/<remedy_id>")
def get_remedy(remedy_id):
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    rec = db.store["recall_remedies"].get(remedy_id)
    if rec is None:
        from errors import ApiError
        raise ApiError("ERR_RECALL_REMEDY_NOT_FOUND", 404, "Recall remedy not found.")
    return ok(rec)
