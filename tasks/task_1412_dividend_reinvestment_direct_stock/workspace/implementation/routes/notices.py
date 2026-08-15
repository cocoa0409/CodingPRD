"""Plan notice endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, clock_dt, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, auth
from response import ok
from services import (
    MIN_NOTICE_DAYS,
    NOTICE_STATUSES,
    NOTICE_TYPES,
    filter_enum,
    get_notice,
    get_plan,
    list_response,
    ser_notice,
    stamp,
    suspend_plan,
    terminate_plan,
    touch,
)
from util import as_enum, as_iso_dt, as_str, body, parse_dt, required

bp = Blueprint("notices", __name__)


@bp.post("/plans/<plan_id>/notices")
def create_notice(plan_id):
    auth(ADMIN)
    get_plan(plan_id)
    data = body()
    notice_type = as_enum(
        required(data, "notice_type"), "notice_type", NOTICE_TYPES
    )
    effective_at = as_iso_dt(required(data, "effective_at"), "effective_at")
    message = as_str(required(data, "message"), "message")
    rec = {
        "id": new_id(),
        "plan_id": plan_id,
        "notice_type": notice_type,
        "message": message,
        "effective_at": effective_at,
        "status": "DRAFT",
        "published_at": None,
    }
    stamp(rec)
    DB["notices"][rec["id"]] = rec
    return ok(ser_notice(rec), status=201)


@bp.get("/plans/<plan_id>/notices")
def list_notices(plan_id):
    auth(ANY_ROLE)
    get_plan(plan_id)
    items = [n for n in DB["notices"].values() if n["plan_id"] == plan_id]
    items = filter_enum(
        items, request.args.get("notice_type"), "notice_type", NOTICE_TYPES,
        "notice_type",
    )
    items = filter_enum(
        items, request.args.get("status"), "status", NOTICE_STATUSES, "status"
    )
    return list_response(items, ser_notice)


@bp.post("/notices/<nid>/publish")
def publish_notice(nid):
    auth(ADMIN)
    n = get_notice(nid)
    if n["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Notice is not DRAFT")
    if parse_dt(n["effective_at"]) - clock_dt() < timedelta(days=MIN_NOTICE_DAYS):
        raise ApiError(
            "ERR_NOTICE_LEAD_TIME_SHORT",
            422,
            "Notice effective_at is less than 10 days after the logical clock",
        )
    n["status"] = "PUBLISHED"
    n["published_at"] = n["published_at"] or None
    from db import logical_now_iso

    n["published_at"] = logical_now_iso()
    touch(n)
    return ok(ser_notice(n))


@bp.post("/notices/<nid>/take-effect")
def take_effect_notice(nid):
    auth(ADMIN)
    n = get_notice(nid)
    if n["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Notice is not PUBLISHED")
    if clock_dt() < parse_dt(n["effective_at"]):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Notice effective_at has not been reached"
        )
    plan = get_plan(n["plan_id"])
    if n["notice_type"] == "SUSPENSION":
        # Guarded: the plan must be ACTIVE.
        if plan["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
        suspend_plan(plan)
    elif n["notice_type"] == "TERMINATION":
        if plan["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Plan is not ACTIVE or SUSPENDED"
            )
        terminate_plan(plan, 0)
    # MODIFICATION notices drive no plan transition.
    n["status"] = "EFFECTIVE"
    touch(n)
    return ok(ser_notice(n))
