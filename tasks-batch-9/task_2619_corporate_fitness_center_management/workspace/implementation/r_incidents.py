"""IncidentReport endpoints (PRD 3.8)."""
from flask import Blueprint, g

import cascades
from core import (ApiError, ROLE_COMPLIANCE_AUDITOR, ROLE_FITNESS_STAFF, ROLE_SITE_MANAGER,
                 bad_request, body, created, find, get_or_404, new_record, now, ok, opt_bool,
                 opt_str, req_enum, req_instant, req_str, require, upd, view, where)
from guards import INCIDENT_TERMINAL, invalid_transition, terminal

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "MODERATE", "SERIOUS")
CAUSES = ("EQUIPMENT", "MEDICAL", "SLIP_FALL", "OTHER")


def _under_review(incident):
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_NOT_UNDER_REVIEW", 409)


@bp.post("/incident-reports")
def file_incident():
    require(ROLE_FITNESS_STAFF, ROLE_SITE_MANAGER)
    data = body()
    contract_id = req_str(data, "contract_id")
    reported_by_staff_id = req_str(data, "reported_by_staff_id")
    occurred_at_utc = req_instant(data, "occurred_at_utc")
    severity = req_enum(data, "severity", SEVERITIES)
    cause_category = req_enum(data, "cause_category", CAUSES)
    narrative = req_str(data, "narrative", 1, 4000)
    member_id = opt_str(data, "member_id", 1)
    asset_id = opt_str(data, "asset_id", 1)
    aed_deployed = opt_bool(data, "aed_deployed", default=False)
    if occurred_at_utc > now():
        raise bad_request("occurred_at_utc may not be later than the current instant")
    get_or_404("contract", contract_id)
    staff = get_or_404("staff", reported_by_staff_id)
    member = get_or_404("member", member_id) if member_id is not None else None
    asset = get_or_404("asset", asset_id) if asset_id is not None else None
    if staff["contract_id"] != contract_id:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    if member is not None and member["contract_id"] != contract_id:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    if asset is not None and asset["contract_id"] != contract_id:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    incident = new_record("incident", {
        "contract_id": contract_id,
        "reported_by_staff_id": reported_by_staff_id,
        "member_id": member_id,
        "asset_id": asset_id,
        "occurred_at_utc": occurred_at_utc,
        "severity": severity,
        "cause_category": cause_category,
        "narrative": narrative,
        "aed_deployed": aed_deployed,
        "status": "REPORTED",
        "reviewed_by_user_id": None,
        "return_count": 0,
        "claim_reference": None,
        "closure_note": None,
    })
    return created(view(incident))


@bp.post("/incident-reports/<iid>/review")
def review_incident(iid):
    require(ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR)
    incident = get_or_404("incident", iid)
    if g.user_id == incident["reported_by_staff_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN", 403)
    data = body()
    opt_str(data, "review_note", 1, 2000)
    terminal(incident["status"] in INCIDENT_TERMINAL)
    if incident["status"] != "REPORTED":
        invalid_transition()
    upd(incident, status="UNDER_REVIEW", reviewed_by_user_id=g.user_id)
    if incident["severity"] == "SERIOUS" and incident["cause_category"] == "EQUIPMENT" and \
            incident.get("asset_id") is not None:
        cascades.incident_equipment_cascade(incident)
    return ok(view(incident))


@bp.post("/incident-reports/<iid>/return")
def return_incident(iid):
    require(ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR)
    incident = get_or_404("incident", iid)
    data = body()
    req_str(data, "return_note", 1, 2000)
    terminal(incident["status"] in INCIDENT_TERMINAL)
    _under_review(incident)
    upd(incident, status="REPORTED", reviewed_by_user_id=None,
        return_count=(incident.get("return_count") or 0) + 1)
    return ok(view(incident))


@bp.post("/incident-reports/<iid>/file-claim")
def file_claim(iid):
    require(ROLE_COMPLIANCE_AUDITOR)
    incident = get_or_404("incident", iid)
    data = body()
    claim_reference = req_str(data, "claim_reference", 1, 120)
    if not claim_reference.strip():
        raise bad_request("claim_reference must be non-empty")
    terminal(incident["status"] in INCIDENT_TERMINAL)
    _under_review(incident)
    member = find("member", incident.get("member_id"))
    if member is None or not where("waiver", member_id=member["id"]):
        raise ApiError("ERR_CLAIM_SUBJECT_REQUIRED", 422)
    upd(incident, status="CLAIM_FILED", claim_reference=claim_reference)
    return ok(view(incident))


@bp.post("/incident-reports/<iid>/close")
def close_incident(iid):
    require(ROLE_COMPLIANCE_AUDITOR)
    incident = get_or_404("incident", iid)
    data = body()
    closure_note = req_str(data, "closure_note", 1, 2000)
    terminal(incident["status"] in INCIDENT_TERMINAL)
    if incident["status"] == "CLAIM_FILED":
        upd(incident, status="CLAIM_CLOSED", closure_note=closure_note)
        return ok(view(incident))
    _under_review(incident)
    upd(incident, status="CLOSED_NO_CLAIM", closure_note=closure_note)
    return ok(view(incident))
