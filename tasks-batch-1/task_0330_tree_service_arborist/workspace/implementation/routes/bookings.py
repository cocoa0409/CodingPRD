"""Booking routes (flat, cross-aggregate) + finalize/release.

Validation order on create (PRD section 2.9):
  existence (FK 404) -> shape (400) -> OCC (412, priority 6)
  -> utility-clearance safety (422, priority 9)
  -> crew/equipment overlap (409, priority 12/13)
  -> resource region match (422, priority 14)
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import calculations
import db
import errors
import lookups
import response
from errors import ApiError
from helpers import as_int, as_number, as_string, get_json_body, parse_pagination
from middleware import ALL_ROLES, require_roles
from services import active_bookings_for_resource, trees_of_wo

bp = Blueprint("bookings", __name__)


def _parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 string.")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, f"{field} must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/bookings")
@require_roles("Dispatcher")
def create_booking():
    body = get_json_body()

    # --- FK existence (priority 4, 404) ---
    work_order_id = as_string(body, "work_order_id")
    wo = lookups.get_work_order(work_order_id)

    # --- shape (priority 5, 400) ---
    if "resource_kind" not in body or body["resource_kind"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: resource_kind.")
    resource_kind = body["resource_kind"]
    if resource_kind not in ("CREW", "EQUIPMENT"):
        raise ApiError(errors.ERR_INVALID_ENUM, 400, f"Illegal resource_kind: {resource_kind!r}.")

    crew_id = body.get("crew_id")
    equipment_id = body.get("equipment_id")
    if crew_id is not None and not isinstance(crew_id, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "crew_id must be a string.")
    if equipment_id is not None and not isinstance(equipment_id, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "equipment_id must be a string.")

    # FK existence for the supplied resource id (404 before shape-mismatch).
    crew = lookups.get_crew(crew_id) if crew_id is not None else None
    equipment = lookups.get_equipment(equipment_id) if equipment_id is not None else None

    # resource_kind must match which of crew_id/equipment_id is supplied.
    if resource_kind == "CREW":
        if crew_id is None or equipment_id is not None:
            raise ApiError(errors.ERR_RESOURCE_KIND_MISMATCH, 400,
                           "resource_kind=CREW requires crew_id and no equipment_id.")
    else:  # EQUIPMENT
        if equipment_id is None or crew_id is not None:
            raise ApiError(errors.ERR_RESOURCE_KIND_MISMATCH, 400,
                           "resource_kind=EQUIPMENT requires equipment_id and no crew_id.")

    # time window
    if "start_at" not in body or body["start_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: start_at.")
    if "end_at" not in body or body["end_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: end_at.")
    start_at = _parse_dt(body["start_at"], "start_at")
    end_at = _parse_dt(body["end_at"], "end_at")
    if not (end_at > start_at):
        raise ApiError(errors.ERR_INVALID_TIME_WINDOW, 400, "end_at must be strictly after start_at.")

    expected_version = as_int(body, "expected_work_order_version")

    # --- OCC (priority 6, 412) — state beats safety ---
    if expected_version != wo["version"]:
        raise ApiError(errors.ERR_STALE_WORK_ORDER_VERSION, 412,
                       "expected_work_order_version is stale.")

    # --- utility-clearance safety (priority 9, 422) ---
    if resource_kind == "CREW":
        wo_near_utility = any(t["near_utility_line"] for t in trees_of_wo(work_order_id))
        if wo_near_utility and not crew["certified_utility_clearance"]:
            raise ApiError(errors.ERR_UTILITY_CLEARANCE_REQUIRED, 422,
                           "A line-clearance-certified crew is required.")

    # --- scheduling overlap (priority 12/13, 409) ---
    if resource_kind == "CREW":
        for other in active_bookings_for_resource("CREW", crew_id):
            if _overlaps(start_at, end_at, other):
                raise ApiError(errors.ERR_CREW_DOUBLE_BOOKED, 409, "Crew is double-booked.")
    else:
        buffer = timedelta(minutes=equipment["mobilization_buffer_minutes"])
        for other in active_bookings_for_resource("EQUIPMENT", equipment_id):
            if _overlaps_buffered(start_at, end_at, other, buffer):
                raise ApiError(errors.ERR_EQUIPMENT_DOUBLE_BOOKED, 409, "Equipment is double-booked.")

    # --- region match (priority 14, 422) ---
    resource = crew if resource_kind == "CREW" else equipment
    if resource["service_area_id"] != wo["service_area_id"]:
        raise ApiError(errors.ERR_RESOURCE_REGION_MISMATCH, 422,
                       "Resource is not in the work order's service area.")

    obj = db.stamp_new({
        "work_order_id": work_order_id,
        "resource_kind": resource_kind,
        "crew_id": crew_id,
        "equipment_id": equipment_id,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "expected_work_order_version": expected_version,
        "actual_hours": None,
        "billed_cost_cents": 0,
        "status": "RESERVED",
        "_start_dt": start_at.isoformat(),
        "_end_dt": end_at.isoformat(),
    })
    db.bookings[obj["id"]] = obj

    # Booking create bumps the work order's version (OCC).
    db.touch(wo)
    return response.success(db.public(obj), 201)


def _booking_window(other):
    return (datetime.fromisoformat(other["_start_dt"]),
            datetime.fromisoformat(other["_end_dt"]))


def _overlaps(start_at, end_at, other):
    o_start, o_end = _booking_window(other)
    # Half-open [start, end): adjacency (end == start) does NOT overlap.
    return start_at < o_end and o_start < end_at


def _overlaps_buffered(start_at, end_at, other, buffer):
    o_start, o_end = _booking_window(other)
    # Buffer added to BOTH sides of the existing window.
    blocked_start = o_start - buffer
    blocked_end = o_end + buffer
    return start_at < blocked_end and blocked_start < end_at


@bp.get("/bookings")
@require_roles(*ALL_ROLES)
def list_bookings():
    limit, offset = parse_pagination()
    items = db.sort_by_created(db.bookings.values())
    wo = request.args.get("work_order_id")
    cid = request.args.get("crew_id")
    eid = request.args.get("equipment_id")
    if wo is not None:
        items = [b for b in items if b["work_order_id"] == wo]
    if cid is not None:
        items = [b for b in items if b["crew_id"] == cid]
    if eid is not None:
        items = [b for b in items if b["equipment_id"] == eid]
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/bookings/<bid>")
@require_roles(*ALL_ROLES)
def get_booking(bid):
    obj = lookups.get_booking(bid)
    return response.success(db.public(obj), 200)


@bp.post("/bookings/<bid>/finalize")
@require_roles("Dispatcher")
def finalize_booking(bid):
    booking = lookups.get_booking(bid)
    body = get_json_body()

    wo = db.work_orders.get(booking["work_order_id"])
    if wo is None or wo["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_WORK_ORDER_NOT_SCHEDULED, 409,
                       "Work order is not SCHEDULED.")
    if booking["status"] != "RESERVED":
        raise ApiError(errors.ERR_BOOKING_NOT_RESERVED, 409, "Booking is not RESERVED.")

    if "actual_hours" not in body or body["actual_hours"] is None:
        raise ApiError(errors.ERR_INVALID_ACTUAL_HOURS, 400, "actual_hours is required.")
    actual_hours = body["actual_hours"]
    if isinstance(actual_hours, bool) or not isinstance(actual_hours, (int, float)):
        raise ApiError(errors.ERR_INVALID_ACTUAL_HOURS, 400, "actual_hours must be a number.")
    if actual_hours <= 0:
        raise ApiError(errors.ERR_INVALID_ACTUAL_HOURS, 400, "actual_hours must be > 0.")

    if booking["resource_kind"] == "CREW":
        rate = db.crews[booking["crew_id"]]["hourly_rate_cents"]
    else:
        rate = db.equipment[booking["equipment_id"]]["hourly_rate_cents"]

    billed = calculations.booking_billed_cost(rate, actual_hours)
    booking["actual_hours"] = actual_hours
    booking["billed_cost_cents"] = billed
    booking["status"] = "FINALIZED"
    db.touch(booking)

    wo["labor_cost_accrued_cents"] += billed
    db.touch(wo)
    return response.success(db.public(booking), 200)


@bp.post("/bookings/<bid>/release")
@require_roles("Dispatcher")
def release_booking(bid):
    booking = lookups.get_booking(bid)
    if booking["status"] != "RESERVED":
        raise ApiError(errors.ERR_BOOKING_NOT_RESERVED, 409, "Booking is not RESERVED.")
    booking["status"] = "RELEASED"
    db.touch(booking)
    return response.success(db.public(booking), 200)
