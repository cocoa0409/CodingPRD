"""Rate schedule endpoints."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from services.core import SIZE_CLASSES, touch
from timeutil import iso_z, parse_iso
from validators import body, paginate, pagination, req_dt, req_enum, req_int, req_str

bp = Blueprint("rates", __name__)


@bp.post("/rate-schedules")
def create_rate_schedule():
    require_roles("AirportManager")
    data = body()
    airport_id = req_str(data, "airport_id")
    airport = db.airports.get(airport_id)
    if airport is None:
        raise ApiError(ERR_NOT_FOUND, "Airport not found", 404)
    size_class = req_enum(data, "size_class", SIZE_CLASSES)
    monthly_rate = req_int(data, "monthly_rate_cents")
    if monthly_rate <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "monthly_rate_cents must be > 0", 400)
    effective_from = req_dt(data, "effective_from")
    raw_to = data.get("effective_to")
    if raw_to is None:
        raise ApiError(ERR_INVALID_REQUEST, "Required field missing: effective_to", 400)
    # The only sanctioned null-equivalent is the explicit string 'OPEN'.
    if raw_to == "OPEN":
        effective_to = "OPEN"
    else:
        try:
            effective_to = iso_z(parse_iso(raw_to))
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, "effective_to must be an ISO8601 datetime or 'OPEN'", 400)
    effective_from_iso = iso_z(effective_from)
    # Replacement rule: a newer schedule with exactly the same effective_from
    # SUPERSEDES the older one; other overlaps stay ACTIVE.
    for existing in db.rate_schedules.values():
        if (
            existing["airport_id"] == airport_id
            and existing["size_class"] == size_class
            and existing["status"] == "ACTIVE"
            and existing["effective_from"] == effective_from_iso
        ):
            existing["status"] = "SUPERSEDED"
            touch(existing)
    schedule = db.new_entity({
        "airport_id": airport_id,
        "size_class": size_class,
        "monthly_rate_cents": monthly_rate,
        "effective_from": effective_from_iso,
        "effective_to": effective_to,
        "status": "ACTIVE",
    })
    db.rate_schedules[schedule["id"]] = schedule
    return success_obj(db.public(schedule), 201)


@bp.get("/rate-schedules")
def list_rate_schedules():
    require_roles(*ALL_ROLES)
    airport_id = request.args.get("airport_id")
    size_class = request.args.get("size_class")
    items = list(db.rate_schedules.values())
    if airport_id is not None:
        items = [r for r in items if r["airport_id"] == airport_id]
    if size_class is not None:
        items = [r for r in items if r["size_class"] == size_class]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total)


@bp.get("/rate-schedules/<rid>")
def get_rate_schedule(rid):
    require_roles(*ALL_ROLES)
    schedule = db.rate_schedules.get(rid)
    if schedule is None:
        raise ApiError(ERR_NOT_FOUND, "Rate schedule not found", 404)
    return success_obj(db.public(schedule), 200)
