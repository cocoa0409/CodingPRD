"""Routes: quality/risk escalations and regulatory reportable events."""

from flask import Blueprint, g, request

import cascades
import db
import derived
import errors
import middleware
from clock import iso_ms
from helpers import (
    ADJUDICATION_OUTCOMES,
    AUTHORITY_CODES,
    ESCALATION_TYPES,
    REVIEW_BRANCHES,
    REVIEW_TRACKS,
    TRIGGER_REASONS,
    check_enum,
    check_string,
    get_body,
    paginate,
    parse_pagination,
    require_present,
    serialize_escalation,
    serialize_event,
    sorted_by_creation,
    stamp_new,
    touch,
)
from response import success_list, success_object
from routes_cases import get_case_or_404
from state import CLOCK

bp = Blueprint("risk", __name__)


def get_escalation_or_404(escalation_id):
    escalation = db.escalations.get(escalation_id)
    if escalation is None:
        raise errors.not_found(
            errors.ERR_ESCALATION_NOT_FOUND, "QualityRiskEscalation not found"
        )
    return escalation


def get_event_or_404(event_id):
    event = db.reportable_events.get(event_id)
    if event is None:
        raise errors.not_found(errors.ERR_EVENT_NOT_FOUND, "ReportableEvent not found")
    return event


# ---------------------------------------------------------------------------
# QualityRiskEscalation
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases/<case_id>/escalations", methods=["POST"])
def create_escalation(case_id):
    middleware.authenticate()
    middleware.require_roles("QualityRiskOfficer")
    body = get_body()
    require_present(body, "escalation_type", "review_track")
    case = get_case_or_404(case_id)
    escalation_type = check_enum(body, "escalation_type", ESCALATION_TYPES, required=True)
    review_track = check_enum(body, "review_track", REVIEW_TRACKS, required=True)
    outcome_note = body.get("outcome_note")
    if outcome_note is not None and not isinstance(outcome_note, str):
        raise errors.invalid_request("outcome_note must be a string")
    escalation = stamp_new()
    escalation.update(
        {
            "case_id": case["id"],
            "escalation_type": escalation_type,
            "source": "MANUAL",
            "status": "FILED",
            "review_track": review_track,
            "compliance_review_done": False,
            "safety_review_done": False,
            "filed_by_id": g.user_id,
            "adjudicated_by_id": None,
            "adjudicated_at": None,
            "outcome_note": outcome_note,
        }
    )
    db.escalations[escalation["id"]] = escalation
    return success_object(serialize_escalation(escalation), 201)


@bp.route("/api/escalations", methods=["GET"])
def list_escalations():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    filed_by = request.args.get("filed_by_id")
    adjudicated_by = request.args.get("adjudicated_by_id")
    escalation_type = request.args.get("escalation_type")
    escalations = list(db.escalations.values())
    if case_id is not None:
        escalations = [e for e in escalations if e["case_id"] == case_id]
    if status is not None:
        escalations = [e for e in escalations if e["status"] == status]
    if filed_by is not None:
        escalations = [e for e in escalations if e["filed_by_id"] == filed_by]
    if adjudicated_by is not None:
        escalations = [e for e in escalations if e["adjudicated_by_id"] == adjudicated_by]
    if escalation_type is not None:
        escalations = [e for e in escalations if e["escalation_type"] == escalation_type]
    escalations = sorted_by_creation(escalations)
    page, total = paginate(escalations, limit, offset)
    return success_list([serialize_escalation(e) for e in page], limit, offset, total)


@bp.route("/api/escalations/<escalation_id>", methods=["GET"])
def get_escalation(escalation_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    escalation = get_escalation_or_404(escalation_id)
    return success_object(serialize_escalation(escalation))


@bp.route("/api/escalations/<escalation_id>/triage", methods=["POST"])
def triage_escalation(escalation_id):
    middleware.authenticate()
    middleware.require_roles("QualityRiskOfficer")
    body = get_body()
    require_present(body, "review_track")
    escalation = get_escalation_or_404(escalation_id)
    if escalation["status"] != "FILED":
        raise errors.api_error(
            errors.ERR_ESCALATION_INVALID_STATE, 409, "Escalation is not FILED"
        )
    escalation["review_track"] = check_enum(body, "review_track", REVIEW_TRACKS, required=True)
    escalation["status"] = "IN_REVIEW"
    touch(escalation)
    return success_object(serialize_escalation(escalation))


@bp.route("/api/escalations/<escalation_id>/complete-review", methods=["POST"])
def complete_review(escalation_id):
    middleware.authenticate()
    middleware.require_roles("QualityRiskOfficer")
    body = get_body()
    require_present(body, "review_branch")
    escalation = get_escalation_or_404(escalation_id)
    if escalation["status"] != "IN_REVIEW":
        raise errors.api_error(
            errors.ERR_ESCALATION_INVALID_STATE, 409, "Escalation is not IN_REVIEW"
        )
    branch = check_enum(body, "review_branch", REVIEW_BRANCHES, required=True)
    if branch == "COMPLIANCE":
        escalation["compliance_review_done"] = True
    else:
        escalation["safety_review_done"] = True
    # Fork-join: REVIEWS_COMPLETE exactly when the track's required branches done.
    track = escalation["review_track"]
    if (
        (track == "COMPLIANCE" and escalation["compliance_review_done"])
        or (track == "SAFETY" and escalation["safety_review_done"])
        or (
            track == "BOTH"
            and escalation["compliance_review_done"]
            and escalation["safety_review_done"]
        )
    ):
        escalation["status"] = "REVIEWS_COMPLETE"
    touch(escalation)
    return success_object(serialize_escalation(escalation))


@bp.route("/api/escalations/<escalation_id>/adjudicate", methods=["POST"])
def adjudicate_escalation(escalation_id):
    middleware.authenticate()
    middleware.require_roles("QualityRiskOfficer")
    body = get_body()
    require_present(body, "outcome")
    escalation = get_escalation_or_404(escalation_id)
    if escalation["status"] != "REVIEWS_COMPLETE":
        raise errors.api_error(
            errors.ERR_ESCALATION_INVALID_STATE,
            409,
            "Escalation is not REVIEWS_COMPLETE",
        )
    # SoD (PRD §2.10): adjudicator != filer, except a 'system'-filed escalation
    # may be adjudicated by anyone otherwise authorized.
    if escalation["filed_by_id"] != "system" and g.user_id == escalation["filed_by_id"]:
        raise errors.api_error(
            errors.ERR_SEGREGATION_OF_DUTIES,
            403,
            "Escalation adjudicator must differ from the filer",
        )
    outcome = check_enum(body, "outcome", ADJUDICATION_OUTCOMES, required=True)
    outcome_note = body.get("outcome_note")
    if outcome_note is not None and not isinstance(outcome_note, str):
        raise errors.invalid_request("outcome_note must be a string")
    now = CLOCK.now()
    escalation["adjudicated_by_id"] = g.user_id
    escalation["adjudicated_at"] = iso_ms(now)
    if outcome_note is not None:
        escalation["outcome_note"] = outcome_note
    if outcome == "SUBSTANTIATED":
        escalation["status"] = "ADJUDICATED_SUBSTANTIATED"
    else:
        escalation["status"] = "ADJUDICATED_UNSUBSTANTIATED"
    touch(escalation)
    if outcome == "SUBSTANTIATED":
        # Cascade: requires_qro_cosign recomputes true (derived), dues expedite,
        # and a ReportableEvent auto-files when the recomputed due lies in the
        # past on an unresolved case (PRD §3.6).
        case = get_case_or_404(escalation["case_id"])
        cascades.expedite_on_substantiation(case, escalation, now)
    return success_object(serialize_escalation(escalation))


# ---------------------------------------------------------------------------
# ReportableEvent
# ---------------------------------------------------------------------------


@bp.route("/api/patient-cases/<case_id>/reportable-events", methods=["POST"])
def create_event(case_id):
    middleware.authenticate()
    middleware.require_roles("QualityRiskOfficer")
    body = get_body()
    require_present(body, "authority_code", "trigger_reason")
    case = get_case_or_404(case_id)
    escalation = None
    escalation_id = body.get("escalation_id")
    if escalation_id is not None:
        if not isinstance(escalation_id, str):
            raise errors.invalid_request("escalation_id must be a string")
        escalation = db.escalations.get(escalation_id)
        if escalation is None:
            raise errors.not_found(
                errors.ERR_ESCALATION_NOT_FOUND, "QualityRiskEscalation not found"
            )
    trigger = body.get("trigger_reason")
    # Cross-aggregate integrity (rung 9).
    if trigger == "ALLEGED_ABUSE":
        if not case["alleged_abuse_flag"]:
            raise errors.api_error(
                errors.ERR_EVENT_TRIGGER_NOT_SUPPORTED,
                409,
                "ALLEGED_ABUSE event requires case.alleged_abuse_flag",
            )
    else:
        # An escalation_id reference is required for every non-abuse trigger.
        if escalation is None:
            raise errors.invalid_request(
                "escalation_id is required unless trigger_reason is ALLEGED_ABUSE"
            )
        if escalation["case_id"] != case["id"] or (
            escalation["status"] != "ADJUDICATED_SUBSTANTIATED"
        ):
            raise errors.api_error(
                errors.ERR_CROSS_REFERENCE_MISMATCH,
                409,
                "Referenced escalation must belong to the path case and be ADJUDICATED_SUBSTANTIATED",
            )
    authority = check_enum(body, "authority_code", AUTHORITY_CODES, required=True)
    trigger = check_enum(body, "trigger_reason", TRIGGER_REASONS, required=True)
    event = stamp_new()
    event.update(
        {
            "case_id": case["id"],
            "escalation_id": escalation["id"] if escalation is not None else None,
            "authority_code": authority,
            "trigger_reason": trigger,
            "status": "PENDING_FILING",
            "filed_at": None,
            "late_filing": False,
        }
    )
    db.reportable_events[event["id"]] = event
    return success_object(serialize_event(event), 201)


@bp.route("/api/reportable-events", methods=["GET"])
def list_events():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = request.args.get("case_id")
    escalation_id = request.args.get("escalation_id")
    status = request.args.get("status")
    events = list(db.reportable_events.values())
    if case_id is not None:
        events = [e for e in events if e["case_id"] == case_id]
    if escalation_id is not None:
        events = [e for e in events if e["escalation_id"] == escalation_id]
    if status is not None:
        events = [e for e in events if e["status"] == status]
    events = sorted_by_creation(events)
    page, total = paginate(events, limit, offset)
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.route("/api/reportable-events/<event_id>", methods=["GET"])
def get_event(event_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    event = get_event_or_404(event_id)
    return success_object(serialize_event(event))


@bp.route("/api/reportable-events/<event_id>/file", methods=["POST"])
def file_event(event_id):
    middleware.authenticate()
    middleware.require_roles("QualityRiskOfficer")
    get_body()
    event = get_event_or_404(event_id)
    if event["status"] != "PENDING_FILING":
        raise errors.api_error(
            errors.ERR_EVENT_INVALID_STATE, 409, "Event is not PENDING_FILING"
        )
    now = CLOCK.now()
    deadline = derived.event_filing_deadline(event)
    event["filed_at"] = iso_ms(now)
    if now <= deadline:
        # Equality counts as on time.
        event["status"] = "FILED"
        event["late_filing"] = False
    else:
        event["status"] = "LATE_FILED"
        event["late_filing"] = True
        # Late cascade: the unit flips STANDARD -> RESTRICTED; while RESTRICTED,
        # new case intake on that unit is rejected.
        case = get_case_or_404(event["case_id"])
        unit = db.hospital_units.get(case["unit_id"])
        if unit is not None and unit["posture"] == "STANDARD":
            unit["posture"] = "RESTRICTED"
            touch(unit)
    touch(event)
    return success_object(serialize_event(event))


@bp.route("/api/reportable-events/<event_id>/acknowledge", methods=["POST"])
def acknowledge_event(event_id):
    middleware.authenticate()
    middleware.require_roles("ComplianceAuditor")
    get_body()  # optional authority_reference is accepted and not persisted
    event = get_event_or_404(event_id)
    if event["status"] not in ("FILED", "LATE_FILED"):
        raise errors.api_error(
            errors.ERR_EVENT_INVALID_STATE, 409, "Event is not FILED or LATE_FILED"
        )
    event["status"] = "ACKNOWLEDGED"
    touch(event)
    return success_object(serialize_event(event))
