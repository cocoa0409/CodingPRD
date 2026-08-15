"""InspectionFinding endpoints (PRD §3.6): raise during an IN_PROGRESS visit,
remediate, verify under segregation of duties."""
from flask import Blueprint, g

from db import logical_now, new_common, store, touch
from errors import err
from middleware import (get_or_404, require_client_scope, require_roles,
                        require_visit_assignment)
from response import Paginator, created, ok
from services.domain import (compromise_facility_lines, recompute_client_nc,
                             suspend_facility_cascade)
from validation import body_json, parse_datetime_value, req_enum, req_str

bp = Blueprint("findings", __name__)

SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
VERIFY_OUTCOMES = ("CLOSED", "FAILED")


@bp.post("/visits/<visit_id>/findings")
def create_finding(visit_id):
    data = body_json()
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description")
    remediation_deadline = None
    if "remediation_deadline" not in data:
        err("ERR_INVALID_REQUEST", "Field 'remediation_deadline' is required")
    remediation_deadline = parse_datetime_value(data.get("remediation_deadline"),
                                                "remediation_deadline")
    require_roles("FieldSupervisor")
    visit = get_or_404(store.visits, visit_id, "Visit")
    require_visit_assignment(visit)
    if visit["status"] != "IN_PROGRESS":
        err("ERR_VISIT_INVALID_STATE",
            "Findings may be raised only while the visit is IN_PROGRESS")
    finding = new_common({
        "visit_id": visit_id,
        "facility_id": visit["facility_id"],
        "severity": severity,
        "description": description,
        "remediation_deadline": remediation_deadline,
        "origin": "MANUAL",
        "status": "OPEN",
    })
    store.findings[finding["id"]] = finding
    facility = store.facilities.get(visit["facility_id"])
    if facility is not None:
        client = store.clients.get(facility["client_id"])
        if client is not None:
            recompute_client_nc(client)
        # A CRITICAL finding fires the same suspension cascade as a no-access
        # declaration, including the equipment compromise.
        if severity == "CRITICAL":
            suspend_facility_cascade(facility)
            compromise_facility_lines(facility)
    return created(finding)


@bp.get("/visits/<visit_id>/findings")
def list_visit_findings(visit_id):
    visit = get_or_404(store.visits, visit_id, "Visit")
    # UNANNOUNCED opacity: the visit is treated as non-existent for
    # ClientContact callers, including through nested paths (PRD §2.5).
    if g.user_role == "ClientContact" and visit["visit_type"] == "UNANNOUNCED":
        err("ERR_NOT_FOUND", "Visit not found")
    p = Paginator()
    rows = [f for f in store.findings.values() if f["visit_id"] == visit_id]
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/findings")
def list_findings():
    p = Paginator()
    rows = list(store.findings.values())
    rows = p.filter(rows, "facility_id")
    rows = p.filter(rows, "visit_id")
    rows = p.filter(rows, "status")
    rows = p.filter(rows, "severity")
    return ok(p(rows), rtype="array", pagination=p)


@bp.get("/findings/<finding_id>")
def get_finding(finding_id):
    return ok(get_or_404(store.findings, finding_id, "Finding"))


@bp.post("/findings/<finding_id>/submit-remediation")
def submit_remediation(finding_id):
    data = body_json()
    req_str(data, "remediation_notes")
    require_roles("ClientContact")
    finding = get_or_404(store.findings, finding_id, "Finding")
    facility = store.facilities.get(finding["facility_id"])
    if facility is not None:
        require_client_scope(facility["client_id"])
    if finding["status"] not in ("OPEN", "REOPENED", "ESCALATED"):
        err("ERR_FINDING_INVALID_STATE",
            "submit-remediation requires finding status OPEN, REOPENED or ESCALATED")
    finding["status"] = "REMEDIATION_SUBMITTED"
    touch(finding)
    if facility is not None:
        client = store.clients.get(facility["client_id"])
        if client is not None:
            recompute_client_nc(client)
    return ok(finding)


@bp.post("/findings/<finding_id>/verify")
def verify_finding(finding_id):
    data = body_json()
    outcome = req_enum(data, "outcome", VERIFY_OUTCOMES)
    new_deadline = None
    if outcome == "FAILED":
        if "new_remediation_deadline" not in data:
            err("ERR_INVALID_REQUEST",
                "Field 'new_remediation_deadline' is required when outcome is FAILED")
        new_deadline = parse_datetime_value(data.get("new_remediation_deadline"),
                                            "new_remediation_deadline")
        if not new_deadline > logical_now():
            err("ERR_INVALID_REQUEST",
                "new_remediation_deadline must be strictly later than the current instant")
    require_roles("FieldSupervisor")
    finding = get_or_404(store.findings, finding_id, "Finding")
    if finding["status"] != "REMEDIATION_SUBMITTED":
        err("ERR_FINDING_INVALID_STATE",
            "verify requires finding status REMEDIATION_SUBMITTED")
    visit = store.visits.get(finding["visit_id"])
    if visit is not None and visit["inspector_user_id"] == g.user_id:
        err("ERR_SEGREGATION_OF_DUTIES_VERIFICATION",
            "The verifier must differ from the visit's inspector")
    if outcome == "CLOSED":
        finding["status"] = "VERIFIED_CLOSED"
        touch(finding)
    else:
        finding["status"] = "REOPENED"
        finding["remediation_deadline"] = new_deadline
        touch(finding)
    facility = store.facilities.get(finding["facility_id"])
    if facility is not None:
        client = store.clients.get(facility["client_id"])
        if client is not None:
            recompute_client_nc(client)
    return ok(finding)
