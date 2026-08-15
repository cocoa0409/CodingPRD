"""RiskAudit and RemediationAction endpoints."""

from flask import Blueprint, request

from db import store, new_id, parse_date
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_AUDIT_NOT_OPEN, ERR_AUDIT_ACTIONS_OPEN,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_contractor_or_404,
    compute_provisional_score, compute_final_score, risk_level_for,
    maybe_restore_standing, EVENT_POINTS,
)

bp = Blueprint("audits", __name__)

AUDIT_TYPES = {"SCREENING", "FIELDWORK"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}


@bp.route("/api/audits", methods=["POST"])
def create_audit():
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    contractor_id = body.get("contractor_id")
    engagement_id = body.get("engagement_id")
    audit_type = body.get("audit_type")

    if not isinstance(contractor_id, str) or not contractor_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "contractor_id is required")
    if engagement_id is not None and not isinstance(engagement_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "engagement_id must be a string or null")
    if audit_type not in AUDIT_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid audit_type")

    get_contractor_or_404(contractor_id)
    if engagement_id is not None and engagement_id not in store.engagements:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Engagement not found")

    provisional = compute_provisional_score(contractor_id, engagement_id)
    audit = {
        "id": new_id(),
        "contractor_id": contractor_id,
        "engagement_id": engagement_id,
        "audit_type": audit_type,
        "provisional_risk_score": provisional,
        "final_risk_score": None,
        "risk_level": risk_level_for(provisional),
        "open_action_count": 0,
        "findings_summary": None,
        "status": "OPEN",
    }
    stamp_new(audit)
    store.audits[audit["id"]] = audit
    return success(audit, status=201)


@bp.route("/api/audits", methods=["GET"])
def list_audits():
    require_auth(ALL_ROLES)
    items = list(store.audits.values())
    for key in ("contractor_id", "engagement_id", "status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]
    items.sort(key=lambda a: a["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_auth(ALL_ROLES)
    a = store.audits.get(aid)
    if a is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Audit not found")
    return success(a)


@bp.route("/api/audits/<aid>/finalize", methods=["POST"])
def finalize_audit(aid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    fieldwork_events = body.get("fieldwork_events")
    findings_summary = body.get("findings_summary")
    if not isinstance(fieldwork_events, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "fieldwork_events must be a list")
    for ev in fieldwork_events:
        et = ev.get("event_type") if isinstance(ev, dict) else ev
        if et not in EVENT_POINTS:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid fieldwork event type")
    if findings_summary is None or not isinstance(findings_summary, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "findings_summary is required")

    audit = store.audits.get(aid)
    if audit is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Audit not found")
    if audit["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "finalize requires OPEN")

    final = compute_final_score(audit["provisional_risk_score"], fieldwork_events)
    audit["final_risk_score"] = final
    audit["risk_level"] = risk_level_for(final)
    audit["findings_summary"] = findings_summary
    audit["status"] = "FINDINGS_FINALIZED"
    touch(audit)

    # standing side effects
    contractor = store.contractors.get(audit["contractor_id"])
    if contractor is not None:
        if audit["risk_level"] == "HIGH" and contractor["standing_status"] == "GOOD_STANDING":
            contractor["standing_status"] = "WATCH"
            touch(contractor)
        elif audit["risk_level"] == "CRITICAL" and contractor["standing_status"] in ("GOOD_STANDING", "WATCH"):
            contractor["standing_status"] = "SUSPENDED_STANDING"
            touch(contractor)

    # compound: HIGH/CRITICAL continues into REMEDIATION
    if audit["risk_level"] in ("HIGH", "CRITICAL"):
        audit["status"] = "REMEDIATION"

    return success(audit)


@bp.route("/api/audits/<aid>/remediation-actions", methods=["POST"])
def create_remediation_action(aid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    description = body.get("description")
    severity = body.get("severity")
    due_date = body.get("due_date")
    if not description or not isinstance(description, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "description is required")
    if severity not in SEVERITIES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid severity")
    if parse_date(due_date) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "due_date must be an ISO date")

    audit = store.audits.get(aid)
    if audit is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Audit not found")
    if audit["status"] not in ("FINDINGS_FINALIZED", "REMEDIATION"):
        raise ApiError(ERR_AUDIT_NOT_OPEN, 409,
                       "Remediation actions require FINDINGS_FINALIZED or REMEDIATION audit")

    action = {
        "id": new_id(),
        "audit_id": aid,
        "description": description,
        "severity": severity,
        "due_date": due_date,
        "status": "OPEN",
        "close_note": "",
    }
    stamp_new(action)
    store.remediation_actions[action["id"]] = action
    audit["open_action_count"] += 1
    touch(audit)
    return success(action, status=201)


@bp.route("/api/audits/<aid>/remediation-actions", methods=["GET"])
def list_remediation_actions(aid):
    require_auth(ALL_ROLES)
    audit = store.audits.get(aid)
    if audit is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Audit not found")
    items = [r for r in store.remediation_actions.values() if r["audit_id"] == aid]
    items.sort(key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/remediation-actions/<raid>/close", methods=["POST"])
def close_remediation_action(raid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    close_note = body.get("close_note", "")
    if outcome not in ("CLOSED", "WAIVED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome must be CLOSED or WAIVED")
    if outcome == "WAIVED" and (not isinstance(close_note, str) or not close_note.strip()):
        raise ApiError(ERR_INVALID_REQUEST, 400, "close_note required when outcome is WAIVED")

    action = store.remediation_actions.get(raid)
    if action is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Remediation action not found")
    if action["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Action is not OPEN")

    action["status"] = outcome
    action["close_note"] = close_note if isinstance(close_note, str) else ""
    touch(action)

    audit = store.audits.get(action["audit_id"])
    if audit is not None:
        audit["open_action_count"] = max(0, audit["open_action_count"] - 1)
        touch(audit)
        if audit["open_action_count"] == 0:
            maybe_restore_standing(audit["contractor_id"])
    return success(action)


@bp.route("/api/audits/<aid>/close", methods=["POST"])
def close_audit(aid):
    require_auth(["ComplianceOfficer"])
    audit = store.audits.get(aid)
    if audit is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Audit not found")
    status = audit["status"]
    if status == "OPEN":
        if audit["audit_type"] != "SCREENING":
            raise ApiError(ERR_INVALID_STATE, 409, "Only SCREENING audits close from OPEN")
        if audit["open_action_count"] > 0:
            raise ApiError(ERR_AUDIT_ACTIONS_OPEN, 409, "Open remediation actions exist")
    elif status == "FINDINGS_FINALIZED":
        if audit["risk_level"] not in ("LOW", "MODERATE"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Finalized HIGH/CRITICAL audits must close from REMEDIATION")
        if audit["open_action_count"] > 0:
            raise ApiError(ERR_AUDIT_ACTIONS_OPEN, 409, "Open remediation actions exist")
    elif status == "REMEDIATION":
        if audit["open_action_count"] > 0:
            raise ApiError(ERR_AUDIT_ACTIONS_OPEN, 409, "Open remediation actions exist")
    else:
        raise ApiError(ERR_INVALID_STATE, 409, "Audit is CLOSED")
    audit["status"] = "CLOSED"
    touch(audit)
    return success(audit)
