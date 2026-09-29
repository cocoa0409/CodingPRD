"""Tarmac delay occupations, deplaning deadlines and contingency reports (PRD 3.5)."""

from flask import Blueprint

import calc
from auth import ADMIN, OPS, authorize
from envelope import created, ok
from errors import ApiError
from store import S, new_row, serialize, touch
from validation import body_fk, field, json_body, must_exist, validate

bp = Blueprint("tarmac", __name__)

EVENT_SPEC = [
    field("flight_segment_id", "string", True),
    field("tarmac_start_utc", "datetime", True),
    field("phase", "enum", True, values=["DEPARTURE", "ARRIVAL"]),
]

OPEN_STATUS = "DELAY_ACTIVE"


def _occupies(event, instant):
    """True when `instant` falls inside the event's occupation interval."""
    if instant < event["tarmac_start_utc"]:
        return False
    end = event["interval_end_utc"]
    if end is None:
        return True
    return instant < end


@bp.post("/compliance/tarmac-delay-events")
def create_event():
    authorize([OPS, ADMIN])
    body = json_body()
    segment = body_fk(body, "flight_segment_id", "flight_segment")
    data = validate(body, EVENT_SPEC)

    start = data["tarmac_start_utc"]
    if start < segment["scheduled_departure_utc"]:
        raise ApiError("ERR_TARMAC_WINDOW_INVALID")

    for existing in calc.events_of(segment["id"]):
        # The new occupation is open-ended, so it intersects any existing one
        # that is still open or that ends strictly after the new start.
        if _occupies(existing, start):
            raise ApiError("ERR_TARMAC_INTERVAL_OVERLAP")
        if existing["tarmac_start_utc"] >= start:
            raise ApiError("ERR_TARMAC_INTERVAL_OVERLAP")

    booking = S.bookings[segment["booking_id"]]
    policy = calc.policy_of(booking)
    row = new_row(
        {
            "flight_segment_id": segment["id"],
            "tarmac_start_utc": start,
            "phase": data["phase"],
            "status": OPEN_STATUS,
            "interval_end_utc": None,
            "deplane_completed_utc": None,
            "exemption_reason": None,
            "exemption_declared_at_utc": None,
            "tarmac_minutes": 0,
            "deadline_minutes": calc.tarmac_deadline_minutes(segment, policy),
            "is_violation": False,
            "report_reference": None,
            "corrective_action_summary": None,
            "report_filed_at_utc": None,
        }
    )
    S.tarmac_delay_events[row["id"]] = row
    return created(serialize(row))


DEPLANE_SPEC = [field("deplane_completed_utc", "datetime", True)]


@bp.post("/compliance/tarmac-delay-events/<event_id>/deplane")
def deplane(event_id):
    authorize([OPS, ADMIN])
    event = must_exist("tarmac_delay_event", event_id)
    body = json_body()
    data = validate(body, DEPLANE_SPEC)

    if event["status"] != OPEN_STATUS:
        raise ApiError("ERR_TARMAC_EVENT_STATE_INVALID")
    instant = data["deplane_completed_utc"]
    if instant <= event["tarmac_start_utc"]:
        raise ApiError("ERR_TARMAC_WINDOW_INVALID")

    minutes = calc.whole_minutes(event["tarmac_start_utc"], instant)
    event["status"] = "DEPLANED"
    event["interval_end_utc"] = instant
    event["deplane_completed_utc"] = instant
    event["tarmac_minutes"] = minutes
    event["is_violation"] = minutes > event["deadline_minutes"]
    touch(event)

    segment = S.flight_segments[event["flight_segment_id"]]
    segment["cumulative_tarmac_minutes"] = segment["cumulative_tarmac_minutes"] + minutes
    touch(segment)
    return ok(serialize(event))


EXEMPTION_SPEC = [
    field("exemption_reason", "enum", True, values=["SAFETY", "SECURITY", "ATC_DIRECTIVE"]),
    field("exemption_declared_at_utc", "datetime", True),
]


@bp.post("/compliance/tarmac-delay-events/<event_id>/claim-exemption")
def claim_exemption(event_id):
    authorize([OPS, ADMIN])
    event = must_exist("tarmac_delay_event", event_id)
    body = json_body()
    data = validate(body, EXEMPTION_SPEC)

    if event["status"] != OPEN_STATUS:
        raise ApiError("ERR_TARMAC_EVENT_STATE_INVALID")
    instant = data["exemption_declared_at_utc"]
    if instant <= event["tarmac_start_utc"]:
        raise ApiError("ERR_TARMAC_WINDOW_INVALID")

    minutes = calc.whole_minutes(event["tarmac_start_utc"], instant)
    if minutes > event["deadline_minutes"]:
        raise ApiError("ERR_EXEMPTION_AFTER_DEADLINE")

    event["status"] = "EXEMPTION_INVOKED"
    event["interval_end_utc"] = instant
    event["exemption_reason"] = data["exemption_reason"]
    event["exemption_declared_at_utc"] = instant
    event["tarmac_minutes"] = minutes
    event["is_violation"] = False
    touch(event)

    segment = S.flight_segments[event["flight_segment_id"]]
    # Exemption-closed minutes stay out of the leg's accumulated tarmac time.
    segment["exempted_tarmac_event_count"] = segment["exempted_tarmac_event_count"] + 1
    touch(segment)
    return ok(serialize(event))


FILE_SPEC = [
    field("report_reference", "string", True, min_len=1, max_len=200),
    field("filed_at_utc", "datetime", True),
    field("corrective_action_summary", "string", False, min_len=1, max_len=1000),
]

CLOSED_OUT_SEGMENT_STATUSES = ("DEPARTED", "ARRIVED", "CANCELLED")


@bp.post("/compliance/tarmac-delay-events/<event_id>/file-report")
def file_report(event_id):
    authorize([ADMIN])
    event = must_exist("tarmac_delay_event", event_id)
    body = json_body()
    data = validate(body, FILE_SPEC)

    if event["status"] not in ("DEPLANED", "EXEMPTION_INVOKED"):
        raise ApiError("ERR_TARMAC_EVENT_STATE_INVALID")

    segment = S.flight_segments[event["flight_segment_id"]]
    if segment["status"] not in CLOSED_OUT_SEGMENT_STATUSES:
        raise ApiError("ERR_SEGMENT_STATE_INVALID")

    summary = data.get("corrective_action_summary")
    if event["is_violation"] and summary is None:
        raise ApiError("ERR_CORRECTIVE_ACTION_REQUIRED")

    event["status"] = "REPORT_FILED"
    event["report_reference"] = data["report_reference"]
    if summary is not None:
        event["corrective_action_summary"] = summary
    event["report_filed_at_utc"] = data["filed_at_utc"]
    touch(event)
    return ok(serialize(event))
