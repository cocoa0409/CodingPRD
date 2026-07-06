"""Workshops and workshop-registrations."""
from datetime import timedelta
from flask import Blueprint, request
from clock import iso_now, get_now, parse_iso
from db import DB
from errors import (
    not_found, invalid_request, invalid_state, unauthorized,
    ApiError, ERR_WORKSHOP_OVERLAP, ERR_WORKSHOP_TOO_LATE, ERR_WORKSHOP_FULL,
)
from middleware import (
    auth_context, require_role, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common, bump
from services.validation import require_fields, require_enum, require_int, require_string

bp = Blueprint("workshops", __name__)

TOPICS = {"REPOTTING", "LIGHT_101", "PROPAGATION", "PEST_CONTROL"}
ROOMS = {"STUDIO_A", "STUDIO_B"}
REG_STATUSES = {"REGISTERED", "ATTENDED", "CANCELLED"}
WORKSHOP_STATUSES = {"SCHEDULED", "COMPLETED", "CANCELLED"}
BUFFER = timedelta(minutes=15)


@bp.post("/workshops")
def create_workshop():
    role, _ = auth_context()
    require_role(role, {"Manager"})
    payload = require_json()
    require_fields(payload, ["title", "topic", "room_id", "start_at", "end_at", "capacity"])
    title = require_string(payload, "title")
    require_enum(payload["topic"], TOPICS, "topic")
    require_enum(payload["room_id"], ROOMS, "room_id")
    start_at = payload["start_at"]
    end_at = payload["end_at"]
    ws = parse_iso(start_at)
    we = parse_iso(end_at)
    if ws is None or we is None or we <= ws:
        raise invalid_request("invalid start_at/end_at")
    capacity = require_int(payload, "capacity", minimum=1)

    # Overlap on room with 15-minute buffer, half-open interval.
    prop_start = ws - BUFFER
    prop_end = we + BUFFER
    for other in DB.workshops.values():
        if other["room_id"] != payload["room_id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        o_ws = parse_iso(other["start_at"])
        o_we = parse_iso(other["end_at"])
        o_start = o_ws - BUFFER
        o_end = o_we + BUFFER
        # Intersect half-open intervals [prop_start, prop_end) and [o_start, o_end).
        if prop_start < o_end and o_start < prop_end:
            raise ApiError(ERR_WORKSHOP_OVERLAP, 409, "workshop overlap")

    entity = {
        **stamp_common(full=True),
        "title": title,
        "topic": payload["topic"],
        "room_id": payload["room_id"],
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "status": "SCHEDULED",
    }
    DB.workshops[entity["id"]] = entity
    return created(entity)


@bp.get("/workshops/<wid>")
def get_workshop(wid):
    role, _ = auth_context()
    require_role(role, {"Anonymous", "Customer", "ShopStaff", "Manager"})
    w = DB.workshops.get(wid)
    if not w:
        raise not_found("Workshop")
    return ok(w)


@bp.post("/workshops/<wid>/register")
def register_workshop(wid):
    role, user_id = auth_context()
    require_role(role, {"Customer"})
    w = DB.workshops.get(wid)
    if not w:
        raise not_found("Workshop")
    payload = require_json()
    require_fields(payload, ["customer_id"])
    cid = payload["customer_id"]
    if user_id != cid:
        raise unauthorized("Customer may only register self")
    if cid not in DB.customers:
        raise not_found("Customer")

    # State precondition — workshop must be SCHEDULED.
    if w["status"] != "SCHEDULED":
        raise invalid_state("workshop not SCHEDULED")

    # Temporal cutoff: clock < start_at - 24h; else ERR_WORKSHOP_TOO_LATE.
    ws = parse_iso(w["start_at"])
    if get_now() >= ws - timedelta(hours=24):
        raise ApiError(ERR_WORKSHOP_TOO_LATE, 422, "too late to register")

    # Capacity.
    count = sum(
        1 for r in DB.workshop_registrations.values()
        if r["workshop_id"] == wid and r["status"] in ("REGISTERED", "ATTENDED")
    )
    if count >= w["capacity"]:
        raise ApiError(ERR_WORKSHOP_FULL, 409, "workshop full")

    entity = {
        **stamp_common(full=True),
        "workshop_id": wid,
        "customer_id": cid,
        "status": "REGISTERED",
    }
    DB.workshop_registrations[entity["id"]] = entity
    return created(entity)


@bp.post("/workshops/<wid>/complete")
def complete_workshop(wid):
    role, _ = auth_context()
    require_role(role, {"Manager"})
    w = DB.workshops.get(wid)
    if not w:
        raise not_found("Workshop")
    if w["status"] != "SCHEDULED":
        raise invalid_state("workshop not SCHEDULED")
    end = parse_iso(w["end_at"])
    if get_now() < end:
        raise invalid_state("workshop not yet at end_at")
    w["status"] = "COMPLETED"
    for r in DB.workshop_registrations.values():
        if r["workshop_id"] == wid and r["status"] == "REGISTERED":
            r["status"] = "ATTENDED"
            bump(r)
    bump(w)
    return ok(w)


@bp.get("/workshop-registrations")
def list_regs():
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    limit, offset = parse_pagination(request.args)
    workshop_id = request.args.get("workshop_id")
    customer_id = request.args.get("customer_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in REG_STATUSES:
        raise invalid_request("invalid status filter")
    rows = list(DB.workshop_registrations.values())
    if workshop_id:
        rows = [r for r in rows if r["workshop_id"] == workshop_id]
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if role == "Customer":
        rows = [r for r in rows if r["customer_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/workshop-registrations/<rid>")
def get_reg(rid):
    role, user_id = auth_context()
    require_role(role, {"Customer", "Manager"})
    r = DB.workshop_registrations.get(rid)
    if not r:
        raise not_found("WorkshopRegistration")
    if role == "Customer" and user_id != r["customer_id"]:
        raise unauthorized("not registration owner")
    return ok(r)
