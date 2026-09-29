"""Turnarounds: opening and freezing the plan, floor execution, rework, sign-off."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes_booking import get_booking
from store import db, now_logical, ordered, stamp_new, touch

bp = Blueprint("orders", __name__)

PLANNABLE_BOOKING_STATES = ("HELD", "CONFIRMED")
PROGRESSABLE = ("PLANNED", "IN_PROGRESS", "REWORK")
REWORKABLE = ("IN_PROGRESS", "READY_FOR_SIGNOFF")
TERMINAL_STAGES = {"floor_stage": "FLOOR_COMPLETE",
                   "seating_stage": "SEATING_COMPLETE",
                   "infra_stage": "BROADCAST_READY"}


def get_order(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_CHANGEOVER_ORDER_NOT_FOUND")
    return order


def _profile_of(booking):
    return db.profiles.get(booking["config_profile_id"]) if booking else None


def _all_terminal(order):
    return all(order[field] == stage for field, stage in TERMINAL_STAGES.items())


def _half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _panel_requirement(order):
    to_booking = db.bookings.get(order["to_booking_id"])
    to_profile = _profile_of(to_booking)
    if to_profile is None:
        return 0
    return calc.required_panel_sets(to_profile)


@bp.post("/changeover-orders")
def create_order():
    user_id, _role = v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    # Ladder 5: shape.
    from_id = v.req_id(payload, "from_booking_id")
    to_id = v.req_id(payload, "to_booking_id")
    crew_headcount = v.req_int(payload, "crew_headcount", 1, 200)
    expected_version = v.plain_int(payload, "expected_venue_version")

    # Ladder 7: existence, body identifiers in declaration order.
    from_booking = get_booking(from_id)
    to_booking = get_booking(to_id)

    # The order's arena is copied from the incoming booking.
    venue = db.venues.get(to_booking["venue_id"])
    # Ladder 8: optimistic concurrency.
    if venue is None or int(venue["version"]) != int(expected_version):
        raise ApiError("ERR_STALE_VENUE_VERSION")

    # Ladder 9: from-state legality on both bookings.
    if from_booking["status"] not in PLANNABLE_BOOKING_STATES:
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    if to_booking["status"] not in PLANNABLE_BOOKING_STATES:
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    # Ladder 14: booking sequence structure, before any window arithmetic.
    if not (to_booking["event_start_utc"] > from_booking["event_end_utc"]):
        raise ApiError("ERR_ORDER_BOOKING_SEQUENCE_INVALID")

    window_start = from_booking["event_end_utc"] + timedelta(
        minutes=int(venue["min_turnaround_buffer_minutes"]))
    window_end = to_booking["event_start_utc"]
    window_minutes = calc.whole_minutes_between(window_start, window_end)
    overnight = calc.overnight_shift_flag(window_start, venue)

    from_profile = _profile_of(from_booking)
    to_profile = _profile_of(to_booking)
    if from_profile is None or to_profile is None:
        raise ApiError("ERR_PROFILE_NOT_FOUND")
    planned = calc.planned_turnaround_minutes(
        from_profile, to_profile, calc.ice_deck_status(venue["id"]),
        crew_headcount, overnight)

    # Ladder 15: temporal feasibility — window conflict, then sufficiency.
    for peer in db.orders.values():
        if peer["venue_id"] != venue["id"]:
            continue
        if peer["status"] in calc.TERMINAL_ORDER_STATES:
            continue
        if _half_open_overlap(window_start, window_end,
                              peer["window_start_utc"], peer["window_end_utc"]):
            raise ApiError("ERR_CHANGEOVER_WINDOW_CONFLICT")
    if window_minutes < planned:
        raise ApiError("ERR_TURNAROUND_WINDOW_INSUFFICIENT")

    # Ladder 16: crew cap, then the debt freeze.
    if crew_headcount > int(venue["crew_headcount_cap"]):
        raise ApiError("ERR_CREW_CAP_EXCEEDED")
    if int(venue["changeover_debt_minutes"]) >= calc.CHANGEOVER_DEBT_FREEZE_MINUTES:
        raise ApiError("ERR_CHANGEOVER_DEBT_FREEZE")

    # Ladder 17: referential scoping.
    if from_booking["venue_id"] != to_booking["venue_id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")

    row = {
        "venue_id": venue["id"],
        "from_booking_id": from_booking["id"],
        "to_booking_id": to_booking["id"],
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "window_minutes": window_minutes,
        "crew_headcount": crew_headcount,
        "overnight_shift": overnight,
        "planned_turnaround_minutes": planned,
        "actual_turnaround_minutes": None,
        "overrun_minutes": 0,
        "floor_stage": "NOT_STARTED",
        "seating_stage": "NOT_STARTED",
        "infra_stage": "NOT_STARTED",
        "status": "PLANNED",
        "rework_count": 0,
        "started_at_utc": None,
        "completed_at_utc": None,
        "opened_by_user_id": user_id,
        "signed_off_by_user_id": None,
        "abandon_reason": None,
    }
    stamp_new(row)
    db.orders[row["id"]] = row
    cascade.bump_venue(venue)
    return created(serial.order(row))


@bp.get("/changeover-orders/<order_id>")
def read_order(order_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.order(get_order(order_id)))


@bp.get("/changeover-orders")
def list_orders():
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    matched = list(db.orders.values())
    for field in ("venue_id", "from_booking_id", "to_booking_id", "status"):
        value = v.filter_arg(field)
        if value is not None:
            matched = [o for o in matched if o[field] == value]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.order(o) for o in page], limit, offset, total)


@bp.post("/changeover-orders/<order_id>/progress")
def progress_order(order_id):
    v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    # Ladder 5: shape.
    dimension = v.req_enum(payload, "dimension", tuple(calc.DIMENSIONS.keys()))
    to_stage = v.req_enum(payload, "to_stage", calc.ALL_STAGES)

    order = get_order(order_id)
    field, stages = calc.DIMENSIONS[dimension]

    # Ladder 9: from-state legality — the compound status, then stage adjacency.
    if order["status"] not in PROGRESSABLE:
        raise ApiError("ERR_INVALID_ORDER_STATE")
    current = order[field]
    index = stages.index(current)
    successor = stages[index + 1] if index + 1 < len(stages) else None
    if to_stage != successor:
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "to_stage must be the immediate successor of the dimension's "
                       "current stage.")

    to_booking = db.bookings.get(order["to_booking_id"])
    # Ladder 10: incoming booking commitment.
    if to_booking is None or to_booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INCOMING_BOOKING_NOT_CONFIRMED")

    # Ladder 13: the floor-protection safety gate.
    if dimension == "FLOOR" and to_stage == "LAYING":
        if calc.issued_floor_panel_sets(order["id"]) < _panel_requirement(order):
            raise ApiError("ERR_FLOOR_PROTECTION_SHORTFALL")

    order[field] = to_stage
    if order["started_at_utc"] is None:
        order["started_at_utc"] = now_logical()
    if _all_terminal(order):
        order["completed_at_utc"] = now_logical()
        order["status"] = "READY_FOR_SIGNOFF"
    else:
        order["status"] = "IN_PROGRESS"
    touch(order)
    return ok(serial.order(order))


@bp.post("/changeover-orders/<order_id>/rework")
def rework_order(order_id):
    v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    dimension = v.req_enum(payload, "dimension", tuple(calc.DIMENSIONS.keys()))
    v.req_str(payload, "reason", 1, 500)

    order = get_order(order_id)
    field, _stages = calc.DIMENSIONS[dimension]
    # Ladder 9: from-state legality.
    if order["status"] not in REWORKABLE:
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order[field] == "NOT_STARTED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "The named dimension has not started, so it cannot be reworked.")

    order[field] = "NOT_STARTED"
    order["rework_count"] = int(order["rework_count"]) + 1
    order["completed_at_utc"] = None
    order["status"] = "REWORK"
    touch(order)
    return ok(serial.order(order))


def _is_covering_changeover(order):
    from_profile = _profile_of(db.bookings.get(order["from_booking_id"]))
    to_profile = _profile_of(db.bookings.get(order["to_booking_id"]))
    if from_profile is None or to_profile is None:
        return False
    return bool(from_profile["requires_ice"]
                and not to_profile["requires_ice"]
                and to_profile["ice_cover_required"])


@bp.post("/changeover-orders/<order_id>/signoff")
def signoff_order(order_id):
    user_id, _role = v.auth(("VenueOperationsDirector",))
    order = get_order(order_id)

    # Ladder 4: segregation of duties.
    if user_id == order["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Ladder 9: from-state legality.
    if order["status"] != "READY_FOR_SIGNOFF":
        raise ApiError("ERR_INVALID_ORDER_STATE")

    covering = _is_covering_changeover(order)
    sheet = calc.live_ice_sheet(order["venue_id"])
    in_service_sheet = sheet if (sheet is not None and sheet["status"] == "IN_SERVICE") else None
    # Ladder 13: a covering turnaround may not be signed onto a sweating deck.
    if covering and in_service_sheet is not None:
        score = calc.condensation_risk_score(in_service_sheet)
        in_service_sheet["condensation_risk_score"] = score
        if score >= calc.CONDENSATION_BLOCK_THRESHOLD:
            raise ApiError("ERR_CONDENSATION_RISK_TOO_HIGH")

    order["status"] = "SIGNED_OFF"
    order["signed_off_by_user_id"] = user_id
    actual = calc.actual_turnaround_minutes(order["started_at_utc"], order["completed_at_utc"])
    order["actual_turnaround_minutes"] = actual
    order["overrun_minutes"] = max(0, actual - int(order["window_minutes"]))
    touch(order)

    venue = db.venues.get(order["venue_id"])
    if venue is not None:
        venue["changeover_debt_minutes"] = int(venue["changeover_debt_minutes"]) \
            + int(order["overrun_minutes"])
    if covering and in_service_sheet is not None:
        cascade.cover_ice_sheet(in_service_sheet)
        touch(in_service_sheet)
    if venue is not None:
        cascade.bump_venue(venue)
    return ok(serial.order(order))


@bp.get("/changeover-orders/<order_id>/readiness")
def order_readiness(order_id):
    v.auth(v.ALL_ROLES)
    order = get_order(order_id)
    to_booking = db.bookings.get(order["to_booking_id"])
    venue = db.venues.get(order["venue_id"])

    reasons = []
    if to_booking is None or to_booking["status"] != "CONFIRMED":
        reasons.append("INCOMING_BOOKING_NOT_CONFIRMED")
    if order["floor_stage"] == "NOT_STARTED":
        if calc.issued_floor_panel_sets(order["id"]) < _panel_requirement(order):
            reasons.append("FLOOR_PROTECTION_SHORTFALL")
    if order["floor_stage"] != "FLOOR_COMPLETE":
        reasons.append("FLOOR_INCOMPLETE")
    if order["seating_stage"] != "SEATING_COMPLETE":
        reasons.append("SEATING_INCOMPLETE")
    if order["infra_stage"] != "BROADCAST_READY":
        reasons.append("INFRA_INCOMPLETE")
    if venue is not None and int(venue["changeover_debt_minutes"]) >= \
            calc.CHANGEOVER_DEBT_FREEZE_MINUTES:
        reasons.append("CHANGEOVER_DEBT_FREEZE")

    window_minutes = int(order["window_minutes"])
    planned = int(order["planned_turnaround_minutes"])
    return ok({
        "order_id": order["id"],
        "status": order["status"],
        "floor_stage": order["floor_stage"],
        "seating_stage": order["seating_stage"],
        "infra_stage": order["infra_stage"],
        "window_minutes": window_minutes,
        "planned_turnaround_minutes": planned,
        "slack_minutes": window_minutes - planned,
        "blocking_reasons": reasons,
    })
