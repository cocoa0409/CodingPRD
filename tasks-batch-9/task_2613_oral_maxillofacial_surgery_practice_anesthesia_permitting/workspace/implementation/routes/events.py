"""Adverse events, morbidity review and the regulator track."""
from datetime import timedelta

from flask import Blueprint

from db import clock_dt, clock_str, db, new_record, ordered, touch
from errors import ApiError
from middleware import actor_id, authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import (EVENT_STATUSES, EVENT_TYPES,
                             REPORTING_WINDOW_HOURS, SEVERITIES, get_case,
                             get_practice, open_permit, path_row,
                             referenced_row)
from services.permit import sentinel_enforcement
from services.practice import recompute_open_adverse_events, touch_practice
from timeutil import fmt_dt, parse_date
from validation import (q_enum, q_string, read_body, v_bool, v_enum, v_id,
                        v_instant, v_not_after, v_string)

bp = Blueprint("events", __name__)


@bp.post("/adverse-events")
def create_event():
    authorize("QualityReviewer", "AnesthesiaCoordinator", "Surgeon")
    body = read_body(required=("case_id", "event_type", "severity", "occurred_at",
                              "narrative"))
    case_id = v_id(body, "case_id")
    event_type = v_enum(body, "event_type", EVENT_TYPES)
    severity = v_enum(body, "severity", SEVERITIES)
    occurred_at = v_instant(body, "occurred_at")
    narrative = v_string(body, "narrative", min_len=1, max_len=2000)
    v_not_after(occurred_at, "occurred_at", clock_dt())

    case = referenced_row(db.cases, case_id)
    practice = get_practice(case["practice_id"])

    reported_at = clock_str()
    deadline = fmt_dt(parse_date(occurred_at)
                      + timedelta(hours=REPORTING_WINDOW_HOURS[severity]))
    event = new_record({
        "case_id": case_id,
        "reviewer_staff_id": None,
        "event_type": event_type,
        "severity": severity,
        "occurred_at": occurred_at,
        "narrative": narrative,
        "reported_at": reported_at,
        "reporting_deadline_at": deadline,
        "late_report": parse_date(reported_at) > parse_date(deadline),
        "status": "REPORTED",
        "regulator_notified": False,
        "corrective_action_required": None,
    })
    db.events[event["id"]] = event

    if practice is not None:
        practice["open_adverse_event_count"] = int(practice["open_adverse_event_count"]) + 1
        touch_practice(practice)
        if severity == "SENTINEL":
            sentinel_enforcement(practice, open_permit(practice["id"]))
    return send(event, 201)


@bp.get("/adverse-events/<event_id>")
def read_event(event_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.events, event_id))


@bp.get("/adverse-events")
def list_events():
    authorize(*ALL_ROLES)
    case_id = q_string("case_id")
    reviewer_staff_id = q_string("reviewer_staff_id")
    severity = q_enum("severity", SEVERITIES)
    status = q_enum("status", EVENT_STATUSES)
    rows = ordered([e for e in db.events.values()
                    if (case_id is None or e["case_id"] == case_id)
                    and (reviewer_staff_id is None or e.get("reviewer_staff_id") == reviewer_staff_id)
                    and (severity is None or e["severity"] == severity)
                    and (status is None or e["status"] == status)])
    return send_list(rows)


@bp.post("/adverse-events/<event_id>/morbidity-review")
def morbidity_review(event_id):
    authorize("QualityReviewer")
    event = path_row(db.events, event_id)
    body = read_body(required=("action",),
                     optional=("reviewer_staff_id", "corrective_action_required"))
    action = v_enum(body, "action", ("OPEN", "SIGN_OFF"))
    reviewer_staff_id = v_id(body, "reviewer_staff_id", default=None)
    corrective_action_required = v_bool(body, "corrective_action_required", default=None)
    case = get_case(event["case_id"])

    if action == "OPEN":
        if reviewer_staff_id is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'reviewer_staff_id' is required to open the review.")
        reviewer = referenced_row(db.staff, reviewer_staff_id)
        if case is not None:
            scope_check(reviewer["practice_id"], case["practice_id"])
            if reviewer_staff_id == case["primary_surgeon_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if event["status"] != "REPORTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["reviewer_staff_id"] = reviewer_staff_id
        event["status"] = "UNDER_MORBIDITY_REVIEW"
        touch(event)
        return send(event)

    if corrective_action_required is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'corrective_action_required' is required to sign off the review.")
    if actor_id() != event.get("reviewer_staff_id"):
        raise ApiError("ERR_ACTOR_NOT_ASSIGNED")
    if event["status"] != "UNDER_MORBIDITY_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    event["corrective_action_required"] = corrective_action_required
    event["status"] = "REVIEW_SIGNED_OFF"
    touch(event)
    return send(event)


@bp.post("/adverse-events/<event_id>/regulator-notification")
def regulator_notification(event_id):
    authorize("QualityReviewer", "PracticeAdministrator")
    event = path_row(db.events, event_id)
    body = read_body(required=("notified_at", "notification_reference"))
    v_instant(body, "notified_at")
    v_string(body, "notification_reference", min_len=1, max_len=120)

    if event["status"] not in ("REPORTED", "UNDER_MORBIDITY_REVIEW", "REVIEW_SIGNED_OFF"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if event["regulator_notified"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    event["regulator_notified"] = True
    touch(event)
    return send(event)


@bp.post("/adverse-events/<event_id>/close")
def close_event(event_id):
    authorize("QualityReviewer")
    event = path_row(db.events, event_id)

    if event["status"] != "REVIEW_SIGNED_OFF":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if event["severity"] in ("SEVERE", "SENTINEL") and not event["regulator_notified"]:
        raise ApiError("ERR_REGULATOR_NOTIFICATION_REQUIRED")

    event["status"] = "CLOSED"
    touch(event)
    case = get_case(event["case_id"])
    practice = get_practice(case["practice_id"]) if case is not None else None
    if practice is not None:
        recompute_open_adverse_events(practice)
        touch_practice(practice)
    return send(event)
