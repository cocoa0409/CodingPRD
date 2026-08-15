"""Maintenance event endpoints and cost allocation (PRD 3.7)."""
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from clock import CLOCK, format_iso, parse_iso
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import maintenance_view, new_common, touch
from util import (
    as_bool,
    as_int,
    as_str,
    body,
    paginate_sorted,
    required,
    to_decimal,
)

bp = Blueprint("maintenance", __name__)


def _get_event(mid):
    m = db.maintenance_events.get(mid)
    if not m:
        raise ApiError("ERR_NOT_FOUND", 404, "Maintenance event not found")
    return m


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.route("/maintenance-events", methods=["POST"])
def create_event():
    require_roles("FleetOps")
    data = body()
    aircraft_id = as_str(required(data, "aircraft_id"), "aircraft_id")
    aircraft = db.aircraft.get(aircraft_id)
    if not aircraft:
        raise ApiError("ERR_NOT_FOUND", 404, "Aircraft not found")
    start_raw = as_str(required(data, "window_start_utc"), "window_start_utc")
    end_raw = as_str(required(data, "window_end_utc"), "window_end_utc")
    cost = as_int(required(data, "cost_cents"), "cost_cents")
    unscheduled = as_bool(
        required(data, "unscheduled_flag"), "unscheduled_flag"
    )
    try:
        start = parse_iso(start_raw)
        end = parse_iso(end_raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "window bounds must be ISO 8601 timestamps")
    if end <= start:
        raise ApiError("ERR_TEMPORAL_INVALID", 422,
                       "window_end_utc must be strictly after window_start_utc")
    if cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "cost_cents must be >= 0")

    rec = new_common()
    rec.update({
        "aircraft_id": aircraft_id,
        "window_start_utc": format_iso(start),
        "window_end_utc": format_iso(end),
        "event_status": "SCHEDULED",
        "cost_cents": cost,
        "unscheduled_flag": unscheduled,
        "completed_at": None,
        "allocations": None,
    })
    db.maintenance_events[rec["id"]] = rec
    return ok(maintenance_view(rec), status=201)


@bp.route("/maintenance-events/<mid>", methods=["GET"])
def get_event(mid):
    require_roles(*ALL_ROLES)
    return ok(maintenance_view(_get_event(mid)))


@bp.route("/maintenance-events", methods=["GET"])
def list_events():
    require_roles(*ALL_ROLES)
    aircraft_id = request.args.get("aircraft_id")
    status = request.args.get("event_status")
    items = list(db.maintenance_events.values())
    if aircraft_id is not None:
        items = [m for m in items if m["aircraft_id"] == aircraft_id]
    if status is not None:
        items = [m for m in items if m["event_status"] == status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([maintenance_view(m) for m in page], total, limit, offset)


@bp.route("/maintenance-events/<mid>/start", methods=["POST"])
def start_event(mid):
    require_roles("FleetOps")
    m = _get_event(mid)
    if m["event_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Maintenance event is already {m['event_status']}")
    if m["event_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Event must be SCHEDULED to start")
    # No other IN_PROGRESS event on the same aircraft.
    for other in db.maintenance_events.values():
        if (other["id"] != m["id"]
                and other["aircraft_id"] == m["aircraft_id"]
                and other["event_status"] == "IN_PROGRESS"):
            raise ApiError("ERR_MAINTENANCE_OVERLAP", 409,
                           "Another maintenance event is IN_PROGRESS on this "
                           "aircraft")
    m["event_status"] = "IN_PROGRESS"
    touch(m)
    aircraft = db.aircraft[m["aircraft_id"]]
    aircraft["aircraft_status"] = "IN_MAINTENANCE"
    touch(aircraft)
    # Unassign overlapping CONFIRMED bookings on this tail.
    ms = parse_iso(m["window_start_utc"])
    me = parse_iso(m["window_end_utc"])
    for b in db.bookings.values():
        if (b["assigned_aircraft_id"] == m["aircraft_id"]
                and b["booking_status"] == "CONFIRMED"):
            bs = parse_iso(b["scheduled_departure_utc"])
            be = bs + timedelta(seconds=float(b["estimated_block_hours"]) * 3600.0)
            if _overlaps(ms, me, bs, be):
                b["assigned_aircraft_id"] = None
                touch(b)
    return ok(maintenance_view(m))


@bp.route("/maintenance-events/<mid>/complete", methods=["POST"])
def complete_event(mid):
    require_roles("FleetOps")
    m = _get_event(mid)
    if m["event_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Maintenance event is already {m['event_status']}")
    if m["event_status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Event must be IN_PROGRESS to complete")
    data = body()
    override = data.get("override_early", False)
    if not isinstance(override, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "override_early must be a boolean")
    if CLOCK.now() < parse_iso(m["window_end_utc"]) and not override:
        raise ApiError("ERR_TEMPORAL_INVALID", 422,
                       "Maintenance window has not ended; pass override_early")

    m["event_status"] = "COMPLETED"
    m["completed_at"] = CLOCK.now_iso()
    touch(m)
    aircraft = db.aircraft[m["aircraft_id"]]
    aircraft["aircraft_status"] = "IN_SERVICE"
    touch(aircraft)

    # Cost allocation across owners holding >=1 ACTIVE share in the class.
    allocations = _allocate(m, aircraft)
    m["allocations"] = allocations  # None when deferred
    return ok(maintenance_view(m))


def _allocate(event, aircraft):
    """Waterfall allocation; returns {owner_id: cents} or None when deferred."""
    class_id = aircraft["class_id"]
    # Gather ACTIVE shares of this class grouped by owner.
    by_owner = {}
    for s in db.shares.values():
        if s["class_id"] == class_id and s["share_status"] == "ACTIVE":
            by_owner.setdefault(s["owner_id"], []).append(s)
    if not by_owner:
        return None  # deferred: cost held on the event

    weights = {}
    for owner_id, shares in by_owner.items():
        w = Decimal(0)
        for s in shares:
            frac = (Decimal(s["fraction_numerator"])
                    / Decimal(s["fraction_denominator"]))
            if event["unscheduled_flag"]:
                consumed = (
                    to_decimal(s["annual_entitlement_hours"] or 0)
                    - to_decimal(s["hours_remaining_cy"] or 0)
                )
                w += frac * consumed
            else:
                w += frac
        weights[owner_id] = w

    total_weight = sum(weights.values())
    pool = event["cost_cents"]
    if total_weight <= 0 or pool <= 0:
        return {oid: 0 for oid in weights}

    raw = {
        oid: (Decimal(pool) * w / total_weight) for oid, w in weights.items()
    }
    floored = {oid: int(math.floor(v)) for oid, v in raw.items()}
    remainder = pool - sum(floored.values())

    owners_sorted = sorted(
        weights.keys(),
        key=lambda oid: (
            -weights[oid],
            db.owners[oid]["created_at"] if oid in db.owners else "",
            oid,
        ),
    )
    i = 0
    while remainder > 0 and owners_sorted:
        floored[owners_sorted[i % len(owners_sorted)]] += 1
        remainder -= 1
        i += 1
    return floored


@bp.route("/maintenance-events/<mid>/cancel", methods=["POST"])
def cancel_event(mid):
    require_roles("FleetOps")
    m = _get_event(mid)
    if m["event_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Maintenance event is already {m['event_status']}")
    if m["event_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Event must be SCHEDULED to cancel")
    m["event_status"] = "CANCELLED"
    touch(m)
    return ok(maintenance_view(m))
