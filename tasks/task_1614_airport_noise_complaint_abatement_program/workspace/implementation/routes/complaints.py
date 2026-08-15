"""Noise complaint intake, correlation, closure, reopen, withdraw (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_complaint
import services
from services import touch, refresh_complainant, recompute_correlation
from util import now, quarter_key_of
from validate import validate, parse_pagination

bp = Blueprint("complaints", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

CHANNELS = ["WEB", "PHONE", "APP", "EMAIL"]
DISTURBANCES = ["LOUD_EVENT", "SLEEP_DISTURBANCE", "LOW_FLYING", "GROUND_RUNUP",
                "VIBRATION", "OTHER"]


def _get_complaint(cid):
    c = db.complaints.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", f"NoiseComplaint {cid} not found")
    return c


def _check_owner(caller, complaint):
    if caller.role == "Complainant" and complaint["complainant_id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "A Complainant may act only on their own complaints")


def _quarter_lock_check(occurred_at):
    for r in db.reports.values():
        if r["status"] == "PUBLISHED" and r["period_start"] <= occurred_at < r["period_end"]:
            raise err("ERR_REPORT_QUARTER_LOCKED",
                      "The quarter containing occurred_at has a published report")


def _auto_notification_for_flight(flight, complaint):
    operator = db.operators.get(flight["operator_id"])
    t = now()
    n = {
        "id": new_id(),
        "operator_id": flight["operator_id"],
        "complaint_id": complaint["id"] if complaint is not None else None,
        "noise_event_id": complaint.get("correlated_event_id") if complaint is not None else None,
        "severity": "ADVISORY",
        "subject": f"Noise advisory: flight {flight['flight_number']}",
        "body": "Automatic advisory: complaint correlation threshold reached.",
        "status": "DRAFT",
        "sent_at": None,
        "due_at": None,
        "acknowledged_at": None,
        "responded_at": None,
        "closed_at": None,
        "response_text": None,
        "escalation_reason": None,
        "closed_outcome": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.notifications[n["id"]] = n
    if operator is not None:
        operator["notifications_draft"] += 1
        touch(operator)


@bp.post("/noise-complaints")
def create_complaint():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("complainant_id", "str", True),
        ("occurred_at", "dt", True),
        ("channel", "enum", True, {"enum": CHANNELS}),
        ("disturbance_type", "enum", True, {"enum": DISTURBANCES}),
        ("narrative", "str", False),
    ])
    require_role(caller, ["Complainant", "CommunityLiaison"])
    # ownership gate precedes body FK existence
    if caller.role == "Complainant" and data["complainant_id"] != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "A Complainant may file only for themselves")
    complainant = db.complainants.get(data["complainant_id"])
    if complainant is None:
        raise err("ERR_COMPLAINANT_NOT_FOUND",
                  f"Complainant {data['complainant_id']} not found")
    _quarter_lock_check(data["occurred_at"])
    t = now()
    c = {
        "id": new_id(),
        "complainant_id": complainant["id"],
        "occurred_at": data["occurred_at"],
        "channel": data["channel"],
        "disturbance_type": data["disturbance_type"],
        "narrative": data.get("narrative"),
        "status": "RECEIVED",
        "correlated_flight_id": None,
        "correlated_event_id": None,
        "correlation_confidence": 0.0,
        "correlation_variant_used": "NONE",
        "substantiation_eligible": False,
        "closure_outcome": None,
        "closed_at": None,
        "reopen_count": 0,
        "info_request_note": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.complaints[c["id"]] = c
    refresh_complainant(complainant)
    return success_object(ser_complaint(c), status=201)


@bp.get("/noise-complaints")
def list_complaints():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.complaints.values(), key=lambda c: c["created_at"])
    f_complainant = request.args.get("complainant_id")
    f_status = request.args.get("status")
    f_quarter = request.args.get("quarter")
    f_flight = request.args.get("correlated_flight_id")
    f_event = request.args.get("correlated_event_id")
    if f_complainant is not None:
        items = [c for c in items if c["complainant_id"] == f_complainant]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    if f_quarter is not None:
        items = [c for c in items if quarter_key_of(c["created_at"]) == f_quarter]
    if f_flight is not None:
        items = [c for c in items if c.get("correlated_flight_id") == f_flight]
    if f_event is not None:
        items = [c for c in items if c.get("correlated_event_id") == f_event]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_complaint(c) for c in page], limit, offset, total)


@bp.get("/noise-complaints/<complaintId>")
def get_complaint(complaintId):
    caller = get_caller()
    require_role(caller, STAFF + ["Complainant"])
    c = _get_complaint(complaintId)
    _check_owner(caller, c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/begin-review")
def begin_review(complaintId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    c = _get_complaint(complaintId)
    if c["status"] != "RECEIVED":
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "begin-review requires status RECEIVED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/request-info")
def request_info(complaintId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("info_request_note", "str", True)])
    require_role(caller, ["NoiseAnalyst"])
    c = _get_complaint(complaintId)
    if c["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "request-info requires status UNDER_REVIEW")
    c["status"] = "AWAITING_COMPLAINANT"
    c["info_request_note"] = data["info_request_note"]
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/provide-info")
def provide_info(complaintId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [("narrative", "str", True)])
    require_role(caller, ["Complainant", "CommunityLiaison"])
    c = _get_complaint(complaintId)
    _check_owner(caller, c)
    if c["status"] != "AWAITING_COMPLAINANT":
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "provide-info requires status AWAITING_COMPLAINANT")
    existing = c.get("narrative")
    c["narrative"] = (existing + "\n" + data["narrative"]) if existing \
        else data["narrative"]
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/correlate")
def correlate(complaintId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("flight_id", "str", False),
        ("noise_event_id", "str", False),
        ("expected_complaint_version", "int", True),
    ])
    require_role(caller, ["NoiseAnalyst"])
    c = _get_complaint(complaintId)
    # gate 7: body FK existence
    flight = None
    event = None
    if data.get("flight_id") is not None:
        flight = db.flights.get(data["flight_id"])
        if flight is None:
            raise err("ERR_FLIGHT_NOT_FOUND",
                      f"FlightOperation {data['flight_id']} not found")
    if data.get("noise_event_id") is not None:
        event = db.events.get(data["noise_event_id"])
        if event is None:
            raise err("ERR_EVENT_NOT_FOUND",
                      f"NoiseEvent {data['noise_event_id']} not found")
    # gate 8: state + OCC
    if c["status"] not in ("UNDER_REVIEW", "CORRELATED"):
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "correlate requires status UNDER_REVIEW or CORRELATED")
    if data["expected_complaint_version"] != c["version"]:
        raise err("ERR_STALE_CORRELATION_VERSION",
                  "expected_complaint_version does not match the complaint version")
    # business guards
    if flight is None and event is None:
        raise err("ERR_CORRELATION_TARGET_REQUIRED",
                  "At least one of flight_id or noise_event_id is required")
    if flight is not None and flight["status"] != "OPERATED":
        raise err("ERR_FLIGHT_NOT_OPERATED",
                  "Correlated flight must be OPERATED")
    if event is not None and event["status"] not in services.CLASSIFIED_FOR_CORRELATION:
        raise err("ERR_EVENT_NOT_CLASSIFIED",
                  "Correlated event must be CLASSIFIED_AIRCRAFT, CLASSIFIED_MIXED or VERIFIED")
    score, variant = services._correlation_score(c, flight, event)
    if score is None:
        raise err("ERR_CORRELATION_WINDOW_EXCEEDED",
                  "No STRICT or RELAXED eligible correlation exists")

    # supersede compensation for a prior live flight link
    old_flight = db.flights.get(c.get("correlated_flight_id") or "")
    if old_flight is not None:
        old_flight["linked_complaint_count"] -= 1
        touch(old_flight)

    c["correlated_flight_id"] = flight["id"] if flight is not None else None
    c["correlated_event_id"] = event["id"] if event is not None else None
    c["correlation_confidence"] = score
    c["correlation_variant_used"] = variant
    c["substantiation_eligible"] = score >= 60.0
    c["status"] = "CORRELATED"

    if flight is not None:
        before = flight["linked_complaint_count"]
        flight["linked_complaint_count"] = before + 1
        touch(flight)
        complainant = db.complainants.get(c["complainant_id"])
        low_priority = complainant is not None and complainant["low_priority_flag"]
        if before < 5 and before + 1 >= 5 and not low_priority:
            _auto_notification_for_flight(flight, c)
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/close")
def close_complaint(complaintId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("outcome", "enum", True, {"enum": ["SUBSTANTIATED", "UNSUBSTANTIATED"]}),
    ])
    require_role(caller, ["NoiseAnalyst"])
    c = _get_complaint(complaintId)
    outcome = data["outcome"]
    if outcome == "SUBSTANTIATED":
        if c["status"] != "CORRELATED":
            raise err("ERR_INVALID_COMPLAINT_STATE",
                      "SUBSTANTIATED close requires status CORRELATED")
        if c["correlation_confidence"] < 60.0:
            raise err("ERR_CONFIDENCE_BELOW_THRESHOLD",
                      "correlation_confidence below 60.0")
        c["status"] = "CLOSED_SUBSTANTIATED"
        c["closure_outcome"] = "SUBSTANTIATED"
        c["closed_at"] = now()
        # a substantiated close never releases the flight link
    else:
        if c["status"] not in ("UNDER_REVIEW", "CORRELATED"):
            raise err("ERR_INVALID_COMPLAINT_STATE",
                      "UNSUBSTANTIATED close requires UNDER_REVIEW or CORRELATED")
        was_correlated = c["status"] == "CORRELATED"
        c["status"] = "CLOSED_UNSUBSTANTIATED"
        c["closure_outcome"] = "UNSUBSTANTIATED"
        c["closed_at"] = now()
        if was_correlated:
            flight = db.flights.get(c.get("correlated_flight_id") or "")
            if flight is not None:
                flight["linked_complaint_count"] -= 1
                touch(flight)
            # unsubstantiated close releases the link
            c["correlated_flight_id"] = None
            c["correlated_event_id"] = None
    complainant = db.complainants.get(c["complainant_id"])
    if complainant is not None:
        refresh_complainant(complainant)
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/reopen")
def reopen_complaint(complaintId):
    caller = get_caller()
    body = get_body()
    validate(body, [("reason", "str", True)])
    require_role(caller, ["Complainant", "CommunityLiaison"])
    c = _get_complaint(complaintId)
    _check_owner(caller, c)
    if c["status"] not in ("CLOSED_SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED"):
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "reopen requires a closed complaint")
    if now() > c["closed_at"] + timedelta(days=30):
        raise err("ERR_REOPEN_WINDOW_EXPIRED",
                  "Reopen window (30 days from closed_at) has expired")
    if c["reopen_count"] >= 3:
        raise err("ERR_REOPEN_LIMIT_REACHED",
                  "Complaint has already been reopened 3 times")
    c["reopen_count"] += 1
    c["closed_at"] = None
    c["status"] = "REOPENED"
    complainant = db.complainants.get(c["complainant_id"])
    if complainant is not None:
        refresh_complainant(complainant)
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/resume-review")
def resume_review(complaintId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    c = _get_complaint(complaintId)
    if c["status"] != "REOPENED":
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "resume-review requires status REOPENED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(ser_complaint(c))


@bp.post("/noise-complaints/<complaintId>/withdraw")
def withdraw_complaint(complaintId):
    caller = get_caller()
    get_body()
    require_role(caller, ["Complainant", "CommunityLiaison"])
    c = _get_complaint(complaintId)
    _check_owner(caller, c)
    if c["status"] == "WITHDRAWN":
        raise err("ERR_INVALID_COMPLAINT_STATE",
                  "Complaint is already WITHDRAWN")
    c["status"] = "WITHDRAWN"
    # cascade D hop 1: linked DRAFT notifications auto-close
    affected_operators = set()
    for n in db.notifications.values():
        if n.get("complaint_id") == c["id"] and n["status"] == "DRAFT":
            n["status"] = "AUTO_CLOSED"
            n["closed_at"] = now()
            n["closed_outcome"] = "COMPLAINT_WITHDRAWN"
            touch(n)
            affected_operators.add(n["operator_id"])
    # cascade D hop 2: operator notification counters
    for op_id in affected_operators:
        op = db.operators.get(op_id)
        if op is not None:
            drafts = sum(1 for x in db.notifications.values()
                         if x["operator_id"] == op_id and x["status"] == "DRAFT")
            opened = sum(1 for x in db.notifications.values()
                         if x["operator_id"] == op_id
                         and x["status"] in services.NOTIFICATION_OPEN_STATES)
            closed = sum(1 for x in db.notifications.values()
                         if x["operator_id"] == op_id
                         and x["status"] in services.NOTIFICATION_CLOSED_STATES)
            op["notifications_draft"] = drafts
            op["notifications_open"] = opened
            op["notifications_closed"] = closed
            touch(op)
    # flight link compensation
    flight = db.flights.get(c.get("correlated_flight_id") or "")
    if flight is not None:
        flight["linked_complaint_count"] -= 1
        touch(flight)
    complainant = db.complainants.get(c["complainant_id"])
    if complainant is not None:
        refresh_complainant(complainant)
    touch(c)
    return success_object(ser_complaint(c))
