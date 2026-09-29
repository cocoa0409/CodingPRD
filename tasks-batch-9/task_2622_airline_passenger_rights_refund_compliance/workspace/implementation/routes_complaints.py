"""Consumer complaints, disability matters and the activity trail (PRD 3.8)."""

from flask import Blueprint, request

import calc
import ledger
from auth import ADMIN, AUDITOR, OFFICER, PASSENGER, authorize, own_booking
from envelope import created, listing, ok
from errors import ApiError
from store import S, add_days, new_row, serialize, touch
from validation import (
    body_fk,
    field,
    json_body,
    must_exist,
    page,
    pagination,
    raw_str,
    validate,
)

bp = Blueprint("complaints", __name__)

CATEGORIES = ["REFUND", "BAGGAGE", "ANCILLARY_SERVICE", "DENIED_BOARDING", "DISABILITY", "OTHER"]
CHANNELS = ["WEB", "EMAIL", "PHONE", "MAIL"]
DISPOSITIONS = ["REFUND_GRANTED", "REFUND_DENIED", "POLICY_EXPLAINED", "ACCOMMODATION_PROVIDED"]
ACCESSIBILITY_CODES = [
    "ASSISTANCE_PROVIDED",
    "EQUIPMENT_REPAIRED",
    "TRAINING_ISSUED",
    "ESCALATED_TO_CRO",
]

FILE_SPEC = [
    field("booking_id", "string", True),
    field("category", "enum", True, values=CATEGORIES),
    field("channel", "enum", True, values=CHANNELS),
    field("received_at_utc", "datetime", True),
    field("summary", "string", True, min_len=1, max_len=500),
]


def _refresh_passenger(booking):
    passenger = ledger.passenger_of(booking)
    if passenger is None:
        return None
    ledger.recompute_open_complaints(passenger)
    touch(passenger)
    return passenger


@bp.post("/compliance/consumer-complaints")
def file_complaint():
    user_id, role = authorize([PASSENGER, OFFICER, ADMIN])
    body = json_body()
    own_booking(user_id, role, raw_str(body, "booking_id"))
    booking = body_fk(body, "booking_id", "booking")
    data = validate(body, FILE_SPEC)

    policy = calc.policy_of(booking)
    received = data["received_at_utc"]
    row = new_row(
        {
            "booking_id": booking["id"],
            "category": data["category"],
            "channel": data["channel"],
            "received_at_utc": received,
            "summary": data["summary"],
            "status": "RECEIVED",
            "ack_due_utc": add_days(received, policy["complaint_ack_deadline_days"]),
            "answer_due_utc": add_days(
                received, calc.answer_days_for(data["category"], policy)
            ),
            "acknowledged_at_utc": None,
            "answered_at_utc": None,
            "info_requested_count": 0,
            "reopen_count": 0,
            "ack_breached": False,
            "answer_breached": False,
            "disposition": None,
            "accessibility_resolution_code": None,
            "granted_amount_cents": None,
        }
    )
    S.consumer_complaints[row["id"]] = row
    ledger.append_activity(row["id"], "RECEIVED", received, role, user_id, data["category"])
    _refresh_passenger(booking)
    return created(serialize(row))


@bp.get("/compliance/consumer-complaints/<complaint_id>")
def read_complaint(complaint_id):
    authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    return ok(serialize(must_exist("consumer_complaint", complaint_id)))


@bp.get("/compliance/consumer-complaints/<complaint_id>/activities")
def list_activities(complaint_id):
    authorize([ADMIN, OFFICER, AUDITOR])
    must_exist("consumer_complaint", complaint_id)
    limit, offset = pagination()
    rows = [
        r for r in S.complaint_activities.values() if r["complaint_id"] == complaint_id
    ]
    rows.sort(key=lambda r: (r["occurred_at_utc"], r["_seq"]))
    activity_type = request.args.get("activity_type")
    if activity_type is not None:
        rows = [r for r in rows if r["activity_type"] == activity_type]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


ACK_SPEC = [field("acknowledged_at_utc", "datetime", True)]


@bp.post("/compliance/consumer-complaints/<complaint_id>/acknowledge")
def acknowledge(complaint_id):
    user_id, role = authorize([OFFICER, ADMIN])
    complaint = must_exist("consumer_complaint", complaint_id)
    data = validate(json_body(), ACK_SPEC)

    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    instant = data["acknowledged_at_utc"]
    if instant < complaint["received_at_utc"]:
        raise ApiError("ERR_ANSWER_BEFORE_RECEIPT")

    complaint["status"] = "ACKNOWLEDGED"
    complaint["acknowledged_at_utc"] = instant
    touch(complaint)
    ledger.append_activity(complaint["id"], "ACKNOWLEDGED", instant, role, user_id, "ACKNOWLEDGED")
    # The complaint is still open, so open_complaint_count does not move (PRD 3.8).
    return ok(serialize(complaint))


INFO_SPEC = [
    field("info_request_note", "string", True, min_len=1, max_len=500),
    field("requested_at_utc", "datetime", True),
]


@bp.post("/compliance/consumer-complaints/<complaint_id>/request-info")
def request_info(complaint_id):
    user_id, role = authorize([OFFICER, ADMIN])
    complaint = must_exist("consumer_complaint", complaint_id)
    data = validate(json_body(), INFO_SPEC)

    if complaint["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    instant = data["requested_at_utc"]
    if complaint["acknowledged_at_utc"] is not None and instant < complaint["acknowledged_at_utc"]:
        raise ApiError("ERR_ANSWER_BEFORE_RECEIPT")

    complaint["status"] = "INFO_REQUESTED"
    complaint["info_requested_count"] += 1
    # answer_due_utc is deliberately NOT extended (PRD 3.8).
    touch(complaint)
    ledger.append_activity(
        complaint["id"], "INFO_REQUESTED", instant, role, user_id, data["info_request_note"]
    )
    return ok(serialize(complaint))


ANSWER_SPEC = [
    field("disposition", "enum", True, values=DISPOSITIONS),
    field("answered_at_utc", "datetime", True),
    field("accessibility_resolution_code", "enum", False, values=ACCESSIBILITY_CODES),
    field("granted_amount_cents", "int", False, cents=True),
]


@bp.post("/compliance/consumer-complaints/<complaint_id>/answer")
def answer(complaint_id):
    user_id, role = authorize([OFFICER, ADMIN])
    complaint = must_exist("consumer_complaint", complaint_id)
    data = validate(json_body(), ANSWER_SPEC)
    disposition = data["disposition"]
    granted = data.get("granted_amount_cents")

    if disposition == "REFUND_GRANTED" and (granted is None or granted < 1):
        raise ApiError("ERR_GRANT_AMOUNT_REQUIRED")

    if complaint["status"] not in ("ACKNOWLEDGED", "INFO_REQUESTED"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")

    code = data.get("accessibility_resolution_code")
    if complaint["category"] == "DISABILITY" and code is None:
        raise ApiError("ERR_ACCESSIBILITY_RESOLUTION_REQUIRED")

    instant = data["answered_at_utc"]
    if instant < complaint["received_at_utc"]:
        raise ApiError("ERR_ANSWER_BEFORE_RECEIPT")

    grants = disposition == "REFUND_GRANTED"
    if grants and ledger.live_grant_for_complaint(complaint["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_OBLIGATION_FOR_SOURCE")

    booking = S.bookings[complaint["booking_id"]]

    # Link two is evaluated before any state is written, because a request-based
    # grant beyond the booking's headroom must fail the whole answer (PRD 3.8).
    if grants:
        obligation = ledger.mint_obligation(
            booking,
            "GOODWILL_GRANT",
            "REQUEST_BASED",
            "GOODWILL_GRANT_AMOUNT",
            granted,
            instant,
            complaint_id=complaint["id"],
        )
    else:
        obligation = None

    complaint["status"] = "ANSWERED"
    complaint["disposition"] = disposition
    complaint["answered_at_utc"] = instant
    if code is not None:
        complaint["accessibility_resolution_code"] = code
    if granted is not None:
        complaint["granted_amount_cents"] = granted
    touch(complaint)
    ledger.append_activity(complaint["id"], "ANSWERED", instant, role, user_id, disposition)
    _refresh_passenger(booking)
    if obligation is not None:
        ledger.bump_booking(booking)
    return ok(serialize(complaint))


REOPEN_SPEC = [
    field("reopen_reason", "string", True, min_len=1, max_len=500),
    field("reopened_at_utc", "datetime", True),
]


@bp.post("/compliance/consumer-complaints/<complaint_id>/reopen")
def reopen(complaint_id):
    user_id, role = authorize([OFFICER, ADMIN])
    complaint = must_exist("consumer_complaint", complaint_id)
    data = validate(json_body(), REOPEN_SPEC)

    if complaint["status"] != "ANSWERED":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    instant = data["reopened_at_utc"]
    if complaint["answered_at_utc"] is not None and instant < complaint["answered_at_utc"]:
        raise ApiError("ERR_ANSWER_BEFORE_RECEIPT")
    if complaint["reopen_count"] >= calc.REOPEN_LIMIT:
        raise ApiError("ERR_REOPEN_LIMIT_REACHED")

    booking = S.bookings[complaint["booking_id"]]
    policy = calc.policy_of(booking)
    complaint["status"] = "ACKNOWLEDGED"
    complaint["reopen_count"] += 1
    complaint["answer_due_utc"] = add_days(
        instant, calc.answer_days_for(complaint["category"], policy)
    )
    complaint["answer_breached"] = False
    # ack_due_utc, disposition and accessibility_resolution_code are retained.
    touch(complaint)
    ledger.append_activity(
        complaint["id"], "REOPENED", instant, role, user_id, data["reopen_reason"]
    )
    _refresh_passenger(booking)
    return ok(serialize(complaint))
