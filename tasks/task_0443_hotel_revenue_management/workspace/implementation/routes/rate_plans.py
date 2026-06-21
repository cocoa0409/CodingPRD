"""RatePlan endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_INVALID_LOS_BAND,
    ERR_MASTER_BAR_EXISTS, ERR_INVALID_STATE,
)
from services.common import (
    get_body, require_str, require_number, opt_number, opt_int, opt_bool,
    stamp_new, bump, parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_rate_plan, ser_rate_decision

bp = Blueprint("rate_plans", __name__)

ALL_ROLES = {"RevenueManager", "GroupSalesManager", "ChannelManager", "Analyst"}
RATE_CLASSES = {"BAR", "CORPORATE", "ADVANCE_PURCHASE", "PACKAGE"}


@bp.route("/rate-plans", methods=["POST"])
def create_rate_plan():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    room_type_id = require_str(body, "room_type_id")

    # rate_class enum.
    if "rate_class" not in body or body["rate_class"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: rate_class")
    rate_class = body["rate_class"]
    if rate_class not in RATE_CLASSES:
        raise err(ERR_INVALID_REQUEST, "rate_class must be one of BAR,CORPORATE,ADVANCE_PURCHASE,PACKAGE")

    is_master_bar = opt_bool(body, "is_master_bar", False)
    min_los = opt_int(body, "min_los", 1)
    if min_los < 1:
        raise err(ERR_INVALID_REQUEST, "min_los must be >= 1")
    max_los = opt_int(body, "max_los", 0)
    if max_los < 0:
        raise err(ERR_INVALID_REQUEST, "max_los must be >= 0")
    base_rate = require_number(body, "base_rate")
    if base_rate < 0:
        raise err(ERR_INVALID_REQUEST, "base_rate must be >= 0")
    floor_rate = require_number(body, "floor_rate")
    if floor_rate < 0:
        raise err(ERR_INVALID_REQUEST, "floor_rate must be >= 0")
    ceiling_rate = require_number(body, "ceiling_rate")
    # ceiling_rate >= floor_rate is a well-formedness rule (ERR_INVALID_REQUEST, §2.9).
    if ceiling_rate < floor_rate:
        raise err(ERR_INVALID_REQUEST, "ceiling_rate must be >= floor_rate")

    # LOS band: max_los > 0 must satisfy max_los >= min_los (ERR_INVALID_LOS_BAND).
    if max_los > 0 and max_los < min_los:
        raise err(ERR_INVALID_LOS_BAND, "max_los must be >= min_los when positive")

    # FK resolution.
    if room_type_id not in db.room_types:
        raise err(ERR_FK_NOT_FOUND, "room_type_id does not reference an existing room type")

    # At most one master BAR per room type.
    if is_master_bar:
        for p in db.rate_plans.values():
            if p["room_type_id"] == room_type_id and p["is_master_bar"]:
                raise err(ERR_MASTER_BAR_EXISTS, "A master BAR plan already exists for this room type")

    rec = {
        "id": new_id(),
        "room_type_id": room_type_id,
        "rate_class": rate_class,
        "is_master_bar": is_master_bar,
        "min_los": min_los,
        "max_los": max_los,
        "base_rate": base_rate,
        "floor_rate": floor_rate,
        "ceiling_rate": ceiling_rate,
        "status": "ACTIVE",
        "published_rate": None,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.rate_plans[rec["id"]] = rec
    return success(ser_rate_plan(rec), status=201)


@bp.route("/rate-plans/<pid>", methods=["GET"])
def get_rate_plan(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.rate_plans, pid)
    return success(ser_rate_plan(rec), status=200)


@bp.route("/rate-plans", methods=["GET"])
def list_rate_plans():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    room_type_id = request.args.get("room_type_id")
    items = [p for p in db.rate_plans.values()
             if room_type_id is None or p["room_type_id"] == room_type_id]
    items = sort_by_created(items)
    total = len(items)
    page = [ser_rate_plan(p) for p in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/rate-plans/<pid>/close", methods=["POST"])
def close_rate_plan(pid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    plan = get_or_404(db.rate_plans, pid)
    # Closing permitted only while ACTIVE.
    if plan["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")
    plan["status"] = "CLOSED"
    # Cascade: every DRAFT rate decision on this plan -> REJECTED, reason "plan closed".
    for d in db.rate_decisions.values():
        if d["rate_plan_id"] == pid and d["status"] == "DRAFT":
            d["status"] = "REJECTED"
            d["reject_reason"] = "plan closed"
            bump(d)
    bump(plan)
    return success(ser_rate_plan(plan), status=200)
