"""InspectionFinding endpoints (PRD 3.2): cyclic remediate/adjudicate loop."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_FINDING_INVALID_STATE,
    ERR_INSPECTION_INVALID_STATE,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.branch import recompute_branch, recompute_inspection_counts
from services.core import new_record, public, touch
from validate import (
    get_body, opt_str, req_date, req_enum, req_str, require_path_resource, require_ref,
)

bp = Blueprint("findings", __name__)

SEVERITIES = ("LOW", "MEDIUM", "HIGH")
DECISIONS = ("VERIFY", "REOPEN")


def _branch_for(finding):
    insp = db["inspections"].get(finding["inspection_id"])
    return db["branches"].get(insp["branch_id"]) if insp is not None else None


@bp.post("/findings")
def create_finding():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    # Priority 3: FK existence
    insp = require_ref("inspections", body.get("inspection_id"), "inspection_id")
    # Priority 4: findings are recorded only while the inspection is IN_PROGRESS
    if insp is not None and insp["status"] != "IN_PROGRESS":
        raise_error(ERR_INSPECTION_INVALID_STATE,
                    "findings can be recorded only on an IN_PROGRESS inspection")
    # Priority 8: schema
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    due_date = req_date(body, "due_date")
    if insp is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: inspection_id")

    rec = new_record("findings", {
        "inspection_id": insp["id"],
        "severity": severity,
        "description": description,
        "due_date": due_date,
        "remediation_note": None,
        "adjudication_note": None,
        "reopen_count": 0,
        "verified_by": None,
        "status": "OPEN",
    })
    # Cascade: inspection counts and branch indicators move in lockstep (PRD 2.7)
    if recompute_inspection_counts(insp):
        touch(insp)
    branch = db["branches"].get(insp["branch_id"])
    if branch is not None and recompute_branch(branch):
        touch(branch)
    return success_object(public(rec), status=201)


@bp.get("/findings")
def list_findings():
    return list_response("findings", filters={
        "inspection_id": request.args.get("inspection_id"),
        "severity": request.args.get("severity"),
        "status": request.args.get("status"),
    })


@bp.get("/findings/<rid>")
def get_finding(rid):
    return get_one("findings", rid)


@bp.post("/findings/<rid>/remediate")
def remediate_finding(rid):
    authorized(["ComplianceAnalyst"])
    finding = require_path_resource("findings", rid)
    if finding["status"] not in ("OPEN", "OVERDUE"):
        raise_error(ERR_FINDING_INVALID_STATE,
                    "remediate is allowed only from OPEN or OVERDUE")
    body = get_body()
    note = req_str(body, "remediation_note")
    finding["remediation_note"] = note
    finding["status"] = "REMEDIATION_SUBMITTED"
    touch(finding)
    insp = db["inspections"].get(finding["inspection_id"])
    if insp is not None and recompute_inspection_counts(insp):
        touch(insp)
    branch = _branch_for(finding)
    if branch is not None and recompute_branch(branch):
        touch(branch)
    return success_object(public(finding))


@bp.post("/findings/<rid>/adjudicate")
def adjudicate_finding(rid):
    caller = authorized(["CompliancePrincipal"])
    finding = require_path_resource("findings", rid)
    if finding["status"] != "REMEDIATION_SUBMITTED":
        raise_error(ERR_FINDING_INVALID_STATE,
                    "adjudicate is allowed only from REMEDIATION_SUBMITTED")
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    rejection_reason = opt_str(body, "rejection_reason")

    if decision == "VERIFY":
        finding["status"] = "VERIFIED_CLOSED"
        finding["verified_by"] = caller.user_id
    else:  # REOPEN: compensates the remediate transition
        finding["status"] = "OPEN"
        finding["reopen_count"] += 1
        finding["adjudication_note"] = rejection_reason
    touch(finding)

    insp = db["inspections"].get(finding["inspection_id"])
    if insp is not None and recompute_inspection_counts(insp):
        touch(insp)
    branch = _branch_for(finding)
    if branch is not None and recompute_branch(branch):
        touch(branch)
    return success_object(public(finding))
