"""Booking endpoints: create, accept, decline, cancel, check-in, mark-no-show, wrap-out."""
from flask import Blueprint, request

from db import STORE, logical_now, parse_dt
from domain import (
    _base,
    call_active_bookings,
    call_nonunion_active,
    call_union_active,
    ser_booking,
    touch,
)
from errors import (
    ApiError,
    ERR_ACTOR_NOT_ELIGIBLE,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_CALL_INVALID_STATE,
    ERR_CALL_NOT_ACCEPTING,
    ERR_DUPLICATE_BOOKING,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_HOLDING_AREA_FULL,
    ERR_HOLDING_AREA_NOT_FOUND,
    ERR_NO_NONUNION_SLOT,
    ERR_NO_SHOW_TOO_EARLY,
    ERR_NO_SLOT_AVAILABLE,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_TURNAROUND_VIOLATION,
    ERR_VALIDATION,
)
from middleware import ALL_ROLES, auth, body, opt_str, req_str
from response import ok_list, ok_obj, paginate
from routes_actors import get_actor
from routes_calls import get_call
from routes_planning import get_area
from routes_productions import get_production
from services import (
    NO_SHOW_GRACE_MINUTES,
    NO_SHOW_SUSPEND_THRESHOLD,
    append_time_event,
    check_turnaround,
    create_booking_record,
    create_replacement_case,
    create_voucher,
    suspend_cascade,
)
from datetime import timedelta

bp = Blueprint("bookings", __name__)


def get_booking(bid):
    b = STORE.bookings.get(bid)
    if b is None:
        raise ApiError(ERR_BOOKING_NOT_FOUND, 404, "Booking not found")
    return b


def _release_slot(booking):
    """Compensating release: slot accounting fields derive from bookings, so the
    observable signal is the owning call's version increment."""
    touch(STORE.casting_calls[booking["casting_call_id"]])


@bp.post("/central-casting/bookings")
def create_booking():
    auth(["CastingAssociate"])
    data = body()
    casting_call_id = req_str(data, "casting_call_id")
    actor_id = req_str(data, "actor_id")
    call = get_call(casting_call_id)
    actor = get_actor(actor_id)
    call_time = None
    if "call_time" in data and data["call_time"] is not None:
        if not isinstance(data["call_time"], str):
            raise ApiError(ERR_VALIDATION, 400, "call_time must be an ISO 8601 datetime")
        call_time = parse_dt(data["call_time"])
        if call_time is None:
            raise ApiError(ERR_VALIDATION, 400, "call_time must be an ISO 8601 datetime")
    # Production phase gate (p7) -> call state (p8) -> eligibility (p10) ->
    # turnaround (p14) -> duplicate (p15) -> slot availability (p16).
    production = get_production(call["production_id"])
    if production["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production must be ACTIVE to book")
    if call["status"] != "PUBLISHED":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Booking requires the call PUBLISHED")
    if actor["status"] != "ELIGIBLE":
        raise ApiError(ERR_ACTOR_NOT_ELIGIBLE, 409, "Actor must be ELIGIBLE to be booked")
    effective_call_time = call_time if call_time is not None else call["general_call_time"]
    expected_wrap = effective_call_time + timedelta(minutes=call["scheduled_duration_minutes"])
    if not check_turnaround(actor["id"], effective_call_time, expected_wrap):
        raise ApiError(
            ERR_TURNAROUND_VIOLATION,
            409,
            "Less than 600 minutes of rest versus another active booking",
        )
    duplicate = any(
        b["actor_id"] == actor["id"]
        and b["casting_call_id"] == call["id"]
        and b["status"] in ("OFFERED", "CONFIRMED", "CHECKED_IN")
        for b in STORE.bookings.values()
    )
    if duplicate:
        raise ApiError(
            ERR_DUPLICATE_BOOKING, 409, "Actor already holds an active booking on this call"
        )
    # union_slot_eligibility: union actors may spill into the shared pool;
    # nonunion actors are capped at nonunion_slots + approved_waiver_reduction.
    total = call["union_slots"] + call["nonunion_slots"]
    consumed = len(call_active_bookings(call["id"]))
    if actor["union_status"] == "SAG_AFTRA":
        if consumed >= total:
            raise ApiError(ERR_NO_SLOT_AVAILABLE, 409, "All slots on this call are consumed")
    else:
        nonunion_cap = call["nonunion_slots"] + call["approved_waiver_reduction"]
        if call_nonunion_active(call["id"]) >= nonunion_cap or consumed >= total:
            raise ApiError(ERR_NO_NONUNION_SLOT, 409, "Nonunion capacity is exhausted")
    booking = create_booking_record(call, actor, effective_call_time)
    touch(call)  # slot consumed: slots_available -1, call version +1
    return ok_obj(ser_booking(booking), code=201)


@bp.get("/central-casting/bookings")
def list_bookings():
    auth(ALL_ROLES)
    rows = sorted(STORE.bookings.values(), key=lambda b: b["_seq"])
    for param in (
        "casting_call_id",
        "actor_id",
        "replacement_case_id",
        "replaces_booking_id",
        "holding_area_id",
        "status",
    ):
        value = request.args.get(param)
        if value is not None:
            rows = [b for b in rows if b.get(param) == value]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_booking(b) for b in page], total, limit, offset)


@bp.get("/central-casting/bookings/<bid>")
def get_booking_route(bid):
    auth(ALL_ROLES)
    return ok_obj(ser_booking(get_booking(bid)))


def _owned_booking(bid, user_id):
    b = get_booking(bid)
    if b["actor_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "Caller does not own this booking")
    return b


@bp.post("/central-casting/bookings/<bid>/accept")
def accept_booking(bid):
    user_id, _ = auth(["BackgroundActor"])
    b = _owned_booking(bid, user_id)
    if b["status"] != "OFFERED":
        raise ApiError(ERR_BOOKING_INVALID_STATE, 409, "Only an OFFERED booking can be accepted")
    call = STORE.casting_calls[b["casting_call_id"]]
    window_open = (not b["is_replacement"] and call["status"] == "PUBLISHED") or (
        b["is_replacement"] and call["status"] == "SHOOTING"
    )
    if not window_open:
        raise ApiError(ERR_CALL_NOT_ACCEPTING, 409, "The acceptance window is closed")
    b["status"] = "CONFIRMED"
    touch(b)
    if b["is_replacement"] and b["replacement_case_id"]:
        case = STORE.replacement_cases.get(b["replacement_case_id"])
        if case is not None and case["status"] == "CANDIDATE_OFFERED":
            case["status"] = "FILLED"
            touch(case)
        for s in STORE.standby_entries.values():
            if (
                s["casting_call_id"] == b["casting_call_id"]
                and s["actor_id"] == b["actor_id"]
                and s["status"] == "ACTIVE"
            ):
                s["status"] = "PROMOTED"
                touch(s)
    return ok_obj(ser_booking(b))


@bp.post("/central-casting/bookings/<bid>/decline")
def decline_booking(bid):
    user_id, _ = auth(["BackgroundActor"])
    b = _owned_booking(bid, user_id)
    if b["status"] != "OFFERED":
        raise ApiError(ERR_BOOKING_INVALID_STATE, 409, "Only an OFFERED booking can be declined")
    b["status"] = "DECLINED"
    touch(b)
    _release_slot(b)
    if b["is_replacement"] and b["replacement_case_id"]:
        case = STORE.replacement_cases.get(b["replacement_case_id"])
        if case is not None and case["status"] == "CANDIDATE_OFFERED":
            case["status"] = "OPEN"
            if b["actor_id"] not in case["excluded_actor_ids"]:
                case["excluded_actor_ids"].append(b["actor_id"])
            case["offered_booking_id"] = None
            case["offered_actor_id"] = None
            touch(case)
    return ok_obj(ser_booking(b))


@bp.post("/central-casting/bookings/<bid>/cancel")
def cancel_booking(bid):
    auth(["CastingAssociate"])
    body()  # optional reason accepted, not persisted
    b = get_booking(bid)
    if b["status"] not in ("OFFERED", "CONFIRMED"):
        raise ApiError(
            ERR_BOOKING_INVALID_STATE,
            409,
            "Only OFFERED or CONFIRMED bookings can be cancelled",
        )
    was_confirmed = b["status"] == "CONFIRMED"
    b["status"] = "CANCELLED"
    touch(b)
    _release_slot(b)
    call = STORE.casting_calls[b["casting_call_id"]]
    if b["is_replacement"] and b["replacement_case_id"]:
        case = STORE.replacement_cases.get(b["replacement_case_id"])
        if case is not None and case["status"] == "CANDIDATE_OFFERED":
            case["status"] = "OPEN"
            if b["actor_id"] not in case["excluded_actor_ids"]:
                case["excluded_actor_ids"].append(b["actor_id"])
            case["offered_booking_id"] = None
            case["offered_actor_id"] = None
            touch(case)
    if was_confirmed and call["status"] == "SHOOTING":
        # Shoot-day cancellation of a confirmed booking opens a replacement case.
        create_replacement_case(b, "CANCELLATION")
    return ok_obj(ser_booking(b))


@bp.post("/central-casting/bookings/<bid>/check-in")
def check_in_booking(bid):
    user_id, _ = auth(["CastingAssociate"])
    data = body()
    b = get_booking(bid)
    area = None
    if "holding_area_id" in data and data["holding_area_id"] is not None:
        if not isinstance(data["holding_area_id"], str):
            raise ApiError(ERR_VALIDATION, 400, "holding_area_id must be a string")
        area = STORE.holding_areas.get(data["holding_area_id"])
        if area is None or area["casting_call_id"] != b["casting_call_id"]:
            raise ApiError(
                ERR_HOLDING_AREA_NOT_FOUND,
                404,
                "Holding area not found for this call",
            )
    if b["status"] != "CONFIRMED":
        raise ApiError(ERR_BOOKING_INVALID_STATE, 409, "Only a CONFIRMED booking can check in")
    call = STORE.casting_calls[b["casting_call_id"]]
    if call["status"] != "SHOOTING":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Check-in requires the call SHOOTING")
    actor = STORE.actors[b["actor_id"]]
    if actor["status"] != "ELIGIBLE":
        raise ApiError(ERR_ACTOR_NOT_ELIGIBLE, 409, "Actor must be ELIGIBLE at check-in")
    if area is not None:
        from domain import area_occupancy

        if area_occupancy(area["id"]) >= area["capacity"]:
            raise ApiError(ERR_HOLDING_AREA_FULL, 409, "Holding area is at capacity")
    append_time_event(b["id"], "CHECK_IN", logical_now(), user_id)
    create_voucher(b["id"])  # exactly one DRAFT voucher per booking, at check-in
    if area is not None:
        b["holding_area_id"] = area["id"]
        touch(area)  # occupancy +1 (derived), area version +1
    b["status"] = "CHECKED_IN"
    touch(b)
    return ok_obj(ser_booking(b))


@bp.post("/central-casting/bookings/<bid>/mark-no-show")
def mark_no_show(bid):
    auth(["CastingAssociate"])
    b = get_booking(bid)
    if b["status"] != "CONFIRMED":
        raise ApiError(ERR_BOOKING_INVALID_STATE, 409, "Only a CONFIRMED booking can be a no-show")
    call = STORE.casting_calls[b["casting_call_id"]]
    if call["status"] != "SHOOTING":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "No-show requires the call SHOOTING")
    if logical_now() < b["call_time"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES):
        raise ApiError(
            ERR_NO_SHOW_TOO_EARLY,
            409,
            "No-show grace period (call_time + 60 minutes) has not elapsed",
        )
    b["status"] = "NO_SHOW"
    touch(b)
    _release_slot(b)  # hop 1: slot released, projected/actual counts recompute
    create_replacement_case(b, "NO_SHOW")  # hop 1: replacement case springs OPEN
    actor = STORE.actors[b["actor_id"]]
    actor["no_show_count"] += 1
    touch(actor)
    if actor["no_show_count"] == NO_SHOW_SUSPEND_THRESHOLD and actor["status"] == "ELIGIBLE":
        # Hop 2: auto-suspension with the full suspension cascade.
        actor["status"] = "SUSPENDED"
        suspend_cascade(actor)
        touch(actor)
    return ok_obj(ser_booking(b))


@bp.post("/central-casting/bookings/<bid>/wrap-out")
def wrap_out_booking(bid):
    user_id, _ = auth(["CastingAssociate"])
    b = get_booking(bid)
    if b["status"] != "CHECKED_IN":
        raise ApiError(ERR_BOOKING_INVALID_STATE, 409, "Only a CHECKED_IN booking can wrap out")
    call = STORE.casting_calls[b["casting_call_id"]]
    if call["status"] != "SHOOTING":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Wrap-out requires the call SHOOTING")
    append_time_event(b["id"], "WRAP_OUT", logical_now(), user_id)
    if b.get("holding_area_id"):
        area = STORE.holding_areas.get(b["holding_area_id"])
        if area is not None:
            touch(area)  # occupancy -1 (derived), area version +1
    b["status"] = "WRAPPED"
    touch(b)
    return ok_obj(ser_booking(b))
