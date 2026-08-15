"""TimeEvent endpoints (append-only ledger with correction chaining)."""
from flask import Blueprint, request

from db import STORE, parse_dt
from domain import EVENT_TYPES, ser_event
from errors import (
    ApiError,
    ERR_BOOKING_INVALID_STATE,
    ERR_BOOKING_NOT_FOUND,
    ERR_TIME_EVENT_INVALID,
    ERR_TIME_EVENT_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import ALL_ROLES, auth, body, req_enum, req_str
from response import ok_list, ok_obj, paginate
from services import append_time_event

bp = Blueprint("time_events", __name__)


def _validate_sequence(booking_id, event_type, occurred_at, corrects_event_id):
    """event_timeline_replay sequence rules, evaluated on the prospective
    effective set (current events plus the new one, correction applied):
    exactly one effective CHECK_IN; at most one effective WRAP_OUT and it must
    follow CHECK_IN; MEAL_IN requires a preceding unmatched MEAL_OUT; no event
    before CHECK_IN; manual WRAP_OUT always rejected."""
    if event_type == "WRAP_OUT":
        raise ApiError(
            ERR_TIME_EVENT_INVALID,
            409,
            "WRAP_OUT is appended only by the wrap-out action",
        )
    existing = [e for e in STORE.time_events.values() if e["booking_id"] == booking_id]
    corrected = {e["corrects_event_id"] for e in existing if e.get("corrects_event_id")}
    if corrects_event_id is not None:
        target = STORE.time_events.get(corrects_event_id)
        if target is None or target["booking_id"] != booking_id:
            raise ApiError(
                ERR_TIME_EVENT_NOT_FOUND,
                404,
                "corrects_event_id target does not exist on this booking",
            )
        if target["id"] in corrected:
            raise ApiError(
                ERR_TIME_EVENT_INVALID,
                409,
                "corrects_event_id target has already been corrected",
            )
        corrected = corrected | {corrects_event_id}
    eff = [e for e in existing if e["id"] not in corrected]
    eff.append(
        {
            "id": "__new__",
            "event_type": event_type,
            "occurred_at": occurred_at,
            "_seq": float("inf"),
        }
    )
    eff.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    check_ins = [e for e in eff if e["event_type"] == "CHECK_IN"]
    if len(check_ins) != 1:
        raise ApiError(
            ERR_TIME_EVENT_INVALID, 409, "Exactly one effective CHECK_IN must exist"
        )
    check_in_at = check_ins[0]["occurred_at"]
    wrap_outs = [e for e in eff if e["event_type"] == "WRAP_OUT"]
    if len(wrap_outs) > 1 or (wrap_outs and wrap_outs[0]["occurred_at"] < check_in_at):
        raise ApiError(
            ERR_TIME_EVENT_INVALID, 409, "WRAP_OUT must be unique and follow CHECK_IN"
        )
    open_meal_out = False
    for e in eff:
        if e["occurred_at"] < check_in_at:
            raise ApiError(ERR_TIME_EVENT_INVALID, 409, "No event may precede the check-in")
        if e["event_type"] == "MEAL_OUT":
            open_meal_out = True
        elif e["event_type"] == "MEAL_IN":
            if not open_meal_out:
                raise ApiError(
                    ERR_TIME_EVENT_INVALID,
                    409,
                    "MEAL_IN requires a preceding unmatched MEAL_OUT",
                )
            open_meal_out = False


@bp.post("/central-casting/time-events")
def create_time_event():
    user_id, _ = auth(["CastingAssociate"])
    data = body()
    booking_id = req_str(data, "booking_id")
    booking = STORE.bookings.get(booking_id)
    if booking is None:
        raise ApiError(ERR_BOOKING_NOT_FOUND, 404, "Booking not found")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    occurred_raw = data.get("occurred_at")
    occurred_at = parse_dt(occurred_raw) if isinstance(occurred_raw, str) else None
    if occurred_at is None:
        raise ApiError(ERR_VALIDATION, 400, "occurred_at must be an ISO 8601 datetime")
    corrects_event_id = data.get("corrects_event_id")
    if corrects_event_id is not None and not isinstance(corrects_event_id, str):
        raise ApiError(ERR_VALIDATION, 400, "corrects_event_id must be a string")
    if booking["status"] not in ("CHECKED_IN", "WRAPPED"):
        raise ApiError(
            ERR_BOOKING_INVALID_STATE,
            409,
            "Time events require the booking CHECKED_IN or WRAPPED",
        )
    _validate_sequence(booking_id, event_type, occurred_at, corrects_event_id)
    event = append_time_event(booking_id, event_type, occurred_at, user_id, corrects_event_id)
    return ok_obj(ser_event(event), code=201)


@bp.get("/central-casting/time-events")
def list_time_events():
    auth(ALL_ROLES)
    rows = sorted(STORE.time_events.values(), key=lambda e: e["_seq"])
    for param in ("booking_id", "event_type", "corrects_event_id"):
        value = request.args.get(param)
        if value is not None:
            rows = [e for e in rows if e.get(param) == value]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_event(e) for e in page], total, limit, offset)


@bp.get("/central-casting/time-events/<eid>")
def get_time_event(eid):
    auth(ALL_ROLES)
    e = STORE.time_events.get(eid)
    if e is None:
        raise ApiError(ERR_TIME_EVENT_NOT_FOUND, 404, "Time event not found")
    return ok_obj(ser_event(e))
