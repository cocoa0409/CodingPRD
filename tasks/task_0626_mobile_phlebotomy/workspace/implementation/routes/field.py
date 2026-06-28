"""Phlebotomists and route days (PRD 3.2)."""
from flask import Blueprint, request

import common
import errors
import serializers
from clock import parse_iso
from db import db, stamp_common, touch
from middleware import require_roles

bp = Blueprint("field", __name__)


# ---------------------------------------------------------------------------
# Phlebotomists
# ---------------------------------------------------------------------------
@bp.post("/phlebotomists")
@require_roles("Dispatcher")
def create_phlebotomist():
    body = common.get_body()
    full_name = common.require_str(body, "full_name")
    territory_code = common.require_str(body, "territory_code")
    certification_active = common.require_bool_optional(body, "certification_active", True)

    rec = {
        "full_name": full_name,
        "territory_code": territory_code,
        "certification_active": certification_active,
        "redraw_strike_count": 0,
        "status": "AVAILABLE",
    }
    stamp_common(rec)
    db.phlebotomists[rec["id"]] = rec
    return common.object_response_201(serializers.phlebotomist(rec))


@bp.get("/phlebotomists")
@require_roles("Dispatcher", "LabOps")
def list_phlebotomists():
    limit, offset = common.get_pagination()
    items = list(db.phlebotomists.values())
    territory = request.args.get("territory_code")
    if territory is not None:
        items = [p for p in items if p["territory_code"] == territory]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.phlebotomist(p) for p in page], limit, offset, total)


@bp.get("/phlebotomists/<rid>")
@require_roles("Dispatcher", "LabOps", "Phlebotomist")
def get_phlebotomist(rid):
    rec = common.find_phlebotomist(rid)
    return common.object_response(serializers.phlebotomist(rec))


# ---------------------------------------------------------------------------
# Route Days
# ---------------------------------------------------------------------------
@bp.post("/phlebotomists/<phleb_id>/route-days")
@require_roles("Dispatcher")
def create_route_day(phleb_id):
    phleb = common.find_phlebotomist(phleb_id)  # path existence (priority 3)
    body = common.get_body()

    territory_code = common.require_str(body, "territory_code")
    service_date = common.require_str(body, "service_date")
    shift_start_raw = common.require_str(body, "shift_start_utc")
    shift_end_raw = common.require_str(body, "shift_end_utc")
    stop_capacity = common.require_int_min(body, "stop_capacity", 1)

    shift_start = parse_iso(shift_start_raw)
    shift_end = parse_iso(shift_end_raw)
    if shift_start is None or shift_end is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "shift_start_utc and shift_end_utc must be ISO 8601.")

    # PRD 3.2: a phlebotomist may not run two overlapping OPEN shifts. Closed-interval
    # semantics: touching endpoints conflict.
    for rd in db.route_days.values():
        if rd["phlebotomist_id"] != phleb_id:
            continue
        if rd["status"] != "OPEN":
            continue
        existing_start = parse_iso(rd["shift_start_utc"])
        existing_end = parse_iso(rd["shift_end_utc"])
        # Closed-interval overlap: a_start <= b_end AND b_start <= a_end.
        if shift_start <= existing_end and existing_start <= shift_end:
            errors.fail(errors.ERR_ROUTE_DAY_SHIFT_OVERLAP,
                        "Shift overlaps an existing OPEN route day for this phlebotomist.")

    rec = {
        "phlebotomist_id": phleb_id,
        "territory_code": territory_code,
        "service_date": service_date,
        "shift_start_utc": shift_start_raw,
        "shift_end_utc": shift_end_raw,
        "stop_capacity": stop_capacity,
        "booked_stop_count": 0,
        "status": "OPEN",
    }
    stamp_common(rec)
    db.route_days[rec["id"]] = rec
    return common.object_response_201(serializers.route_day(rec))


@bp.get("/phlebotomists/<phleb_id>/route-days")
@require_roles("Dispatcher", "LabOps")
def list_route_days(phleb_id):
    common.find_phlebotomist(phleb_id)
    limit, offset = common.get_pagination()
    items = [rd for rd in db.route_days.values() if rd["phlebotomist_id"] == phleb_id]
    service_date = request.args.get("service_date")
    if service_date is not None:
        items = [rd for rd in items if rd["service_date"] == service_date]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.route_day(rd) for rd in page], limit, offset, total)


@bp.get("/route-days/<rid>")
@require_roles("Dispatcher", "LabOps")
def get_route_day(rid):
    rec = common.find_route_day(rid)
    return common.object_response(serializers.route_day(rec))


@bp.get("/route-days/<rid>/appointments")
@require_roles("Dispatcher", "LabOps")
def list_route_day_appointments(rid):
    common.find_route_day(rid)
    limit, offset = common.get_pagination()
    items = [a for a in db.appointments.values() if a["route_day_id"] == rid]
    items = common.sort_by_created(items)
    page, total = common.paginate(items, limit, offset)
    return common.array_response([serializers.appointment(a) for a in page], limit, offset, total)


@bp.post("/route-days/<rid>/close")
@require_roles("Dispatcher")
def close_route_day(rid):
    rec = common.find_route_day(rid)
    rec["status"] = "CLOSED"
    touch(rec)
    return common.object_response(serializers.route_day(rec))
