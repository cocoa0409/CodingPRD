"""Corrective actions: response, review and escalation (PRD sec 3.7)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.common import require_owner, require_state
from services import cascades
from services import calculations as calc
from services import lookup
from services import serializers as ser

bp = Blueprint("corrective_actions", __name__)

REVIEWER = mw.ROLE_STATE_AGENCY_REVIEWER
SPONSOR_ADMIN = mw.ROLE_SPONSOR_ADMIN
MONITOR = mw.ROLE_FIELD_MONITOR

ACTION_STATUSES = ("OPEN", "RESPONSE_SUBMITTED", "REJECTED", "CLOSED", "ESCALATED")
ORIGINS = ("VISIT_FINDING", "COMPLIANCE_FLAG")
UNRESOLVED = ("OPEN", "RESPONSE_SUBMITTED", "REJECTED", "ESCALATED")


@bp.get("/sfsp/corrective-actions/<action_id>")
@mw.endpoint([REVIEWER, SPONSOR_ADMIN, MONITOR])
def get_action(action_id):
    action = lookup.require_action(action_id)
    return response.object_response(ser.corrective_action(action))


@bp.get("/sfsp/corrective-actions")
@mw.endpoint([REVIEWER, SPONSOR_ADMIN, MONITOR])
def list_actions():
    limit, offset = mw.pagination()
    site_id = mw.query_value("site_id")
    visit_id = mw.query_value("monitoring_visit_id")
    parent_id = mw.query_value("follow_up_of_corrective_action_id")
    status = mw.query_enum("status", ACTION_STATUSES)
    severity = mw.query_enum("severity", calc.SEVERITIES)
    origin = mw.query_enum("origin", ORIGINS)

    rows = []
    for action in db.store.actions.values():
        if site_id is not None and action["site_id"] != site_id:
            continue
        if visit_id is not None and action["monitoring_visit_id"] != visit_id:
            continue
        if (
            parent_id is not None
            and action["follow_up_of_corrective_action_id"] != parent_id
        ):
            continue
        if status is not None and action["status"] != status:
            continue
        if severity is not None and action["severity"] != severity:
            continue
        if origin is not None and action["origin"] != origin:
            continue
        rows.append(action)
    return response.paginate(rows, limit, offset, ser.corrective_action)


@bp.post("/sfsp/corrective-actions/<action_id>/response")
@mw.endpoint([SPONSOR_ADMIN])
def submit_response(action_id):
    body = mw.json_body()
    response_note = mw.field_str(body, "response_note")
    evidence_ref = mw.field_str(body, "evidence_ref", required=False)

    action = lookup.require_action(action_id)
    site = lookup.require_site(action["site_id"])
    require_owner(site["sponsor_id"])
    require_state(action["status"] in ("OPEN", "REJECTED"), "ERR_ACTION_STATE_INVALID")

    action["response_note"] = response_note
    action["evidence_ref"] = evidence_ref
    action["status"] = "RESPONSE_SUBMITTED"
    db.touch(action)
    return response.object_response(ser.corrective_action(action))


@bp.post("/sfsp/corrective-actions/<action_id>/review")
@mw.endpoint([MONITOR])
def review_action(action_id):
    body = mw.json_body()
    decision = mw.field_enum(body, "decision", ("CLOSED", "REJECTED"))
    reason = mw.field_str(body, "reason", required=False)
    if decision == "REJECTED" and reason is None:
        mw.bad_request("Field 'reason' is required for a REJECTED decision.")

    action = lookup.require_action(action_id)
    reviewer = mw.acting_user_id()
    if reviewer == action["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    require_state(action["status"] == "RESPONSE_SUBMITTED", "ERR_ACTION_STATE_INVALID")

    site = lookup.require_site(action["site_id"])

    if decision == "CLOSED":
        action["status"] = "CLOSED"
        action["closed_by_user_id"] = reviewer
        db.touch(action)
        cascades.maybe_reinstate_after_closure(site, action)
        cascades.maybe_close_visit(action)
    else:
        action["status"] = "REJECTED"
        action["rejection_count"] = (action["rejection_count"] or 0) + 1
        db.touch(action)
        cascades.create_corrective_action(
            site,
            severity=calc.next_severity(action["severity"]),
            finding_code=action["finding_code"],
            origin="VISIT_FINDING",
            opened_by_user_id=reviewer,
            monitoring_visit_id=action["monitoring_visit_id"],
            follow_up_of_corrective_action_id=action["id"],
        )

    return response.object_response(ser.corrective_action(action))


@bp.post("/sfsp/corrective-actions/<action_id>/escalate")
@mw.endpoint([REVIEWER])
def escalate_action(action_id):
    body = mw.json_body()
    mw.field_str(body, "reason")

    action = lookup.require_action(action_id)
    require_state(action["status"] in ("OPEN", "REJECTED"), "ERR_ACTION_STATE_INVALID")

    due_date = db.parse_date(action["due_date"])
    overdue = due_date is not None and db.clock.today() > due_date
    twice_rejected = (
        action["status"] == "REJECTED"
        and (action["rejection_count"] or 0) >= calc.ESCALATION_REJECTION_THRESHOLD
    )
    if not overdue and not twice_rejected:
        raise ApiError("ERR_ESCALATION_NOT_DUE")

    action["status"] = "ESCALATED"
    db.touch(action)

    site = lookup.require_site(action["site_id"])
    if site["approval_status"] == "APPROVED":
        cascades.suspend_site(site, "CORRECTIVE_ACTION_ESCALATED")
    else:
        cascades.raise_claim_hold(site)

    return response.object_response(ser.corrective_action(action))
