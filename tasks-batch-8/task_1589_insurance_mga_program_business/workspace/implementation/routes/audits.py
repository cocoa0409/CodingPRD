"""Carrier audits: schedule/start/findings/remediation/close/escalate, with
the escalation program-suspension cascade (PRD section 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, err, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_AUDIT_WINDOW_GAP, ERR_AUDIT_WINDOW_NOT_OPEN,
    ERR_UNRESOLVED_CRITICAL_FINDINGS, ERR_NO_CRITICAL_FINDING,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services import cascades
from validation import get_body, req_enum, req_datetime, req_list

bp = Blueprint("audits", __name__)

AUDIT_SCOPES = {"UNDERWRITING", "CLAIMS", "TRUST_ACCOUNTING", "FULL"}
AUDIT_OUTCOMES = {"SATISFACTORY", "CORRECTIVE_ACTION", "TERMINATION_RECOMMENDED"}
FINDING_SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
AUDIT_MIN_GAP_DAYS = 30
NON_TERMINAL_AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED", "REMEDIATION")


def _validate_findings(findings):
    out = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise err(ERR_INVALID_REQUEST, "Finding %d must be an object." % i)
        finding_id = f.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            raise err(ERR_INVALID_REQUEST, "Finding %d requires a non-empty 'finding_id'." % i)
        severity = f.get("severity")
        if severity not in FINDING_SEVERITIES:
            raise err(ERR_INVALID_REQUEST, "Finding %d has an invalid severity." % i)
        description = f.get("description")
        if description is not None and not isinstance(description, str):
            raise err(ERR_INVALID_REQUEST, "Finding %d 'description' must be a string." % i)
        resolved = f.get("resolved", False)
        if not isinstance(resolved, bool):
            raise err(ERR_INVALID_REQUEST, "Finding %d 'resolved' must be a boolean." % i)
        out.append({
            "finding_id": finding_id,
            "severity": severity,
            "description": description,
            "resolved": resolved,
        })
    return out


@bp.post("/mga/programs/<programId>/audits")
def create_audit(programId):
    require_roles("CarrierAuditor")
    program = get_or_404(STORE.programs, programId, "Program")
    body = get_body()
    scope = req_enum(body, "scope", AUDIT_SCOPES)
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    if scheduled_start > scheduled_end:
        raise_err(ERR_INVALID_REQUEST, "scheduled_start may not fall after scheduled_end.")
    require_program_not_terminal(program)
    gap = timedelta(days=AUDIT_MIN_GAP_DAYS)
    for o in STORE.carrier_audits.values():
        if (
            o["program_id"] == program["id"]
            and o["status"] in NON_TERMINAL_AUDIT_STATUSES
            and not (
                (scheduled_start - o["scheduled_end"]) >= gap
                or (o["scheduled_start"] - scheduled_end) >= gap
            )
        ):
            raise_err(
                ERR_AUDIT_WINDOW_GAP,
                "Audit window is within 30 days of another non-terminal audit of the same program.",
            )
    a = new_entity()
    a.update({
        "program_id": program["id"],
        "scope": scope,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "findings": [],
        "status": "SCHEDULED",
        "outcome": None,
    })
    STORE.carrier_audits[a["id"]] = a
    return success_object(serialize.audit(a), status=201)


@bp.get("/mga/programs/<programId>/audits")
def list_program_audits(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [a for a in STORE.carrier_audits.values() if a["program_id"] == programId],
        status=request.args.get("status"),
    )
    return render_list(items, serialize.audit)


@bp.get("/mga/audits/<auditId>")
def get_audit(auditId):
    require_roles(*ALL_ROLES)
    a = get_or_404(STORE.carrier_audits, auditId, "CarrierAudit")
    return success_object(serialize.audit(a))


@bp.get("/mga/audits")
def list_audits():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.carrier_audits.values()),
        program_id=request.args.get("program_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.audit)


@bp.post("/mga/audits/<auditId>/start")
def start_audit(auditId):
    require_roles("CarrierAuditor")
    a = get_or_404(STORE.carrier_audits, auditId, "CarrierAudit")
    if a["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED audit can be started.")
    if now_dt() < a["scheduled_start"]:
        raise_err(ERR_AUDIT_WINDOW_NOT_OPEN, "The audit window has not opened yet.")
    a["status"] = "IN_PROGRESS"
    touch(a)
    return success_object(serialize.audit(a))


@bp.post("/mga/audits/<auditId>/issue-findings")
def issue_findings(auditId):
    require_roles("CarrierAuditor")
    a = get_or_404(STORE.carrier_audits, auditId, "CarrierAudit")
    body = get_body()
    findings = _validate_findings(req_list(body, "findings"))
    if a["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "Only an IN_PROGRESS audit can issue findings.")
    a["findings"] = findings
    a["status"] = "FINDINGS_ISSUED"
    touch(a)
    return success_object(serialize.audit(a))


@bp.post("/mga/audits/<auditId>/submit-remediation")
def submit_remediation(auditId):
    require_roles("MGAUnderwriter")
    a = get_or_404(STORE.carrier_audits, auditId, "CarrierAudit")
    body = get_body()
    resolved_finding_ids = req_list(body, "resolved_finding_ids")
    for v in resolved_finding_ids:
        if not isinstance(v, str):
            raise err(ERR_INVALID_REQUEST, "Field 'resolved_finding_ids' must be an array of strings.")
    if a["status"] != "FINDINGS_ISSUED":
        raise_err(ERR_INVALID_STATE, "Only a FINDINGS_ISSUED audit can accept remediation.")
    ids = set(resolved_finding_ids)
    for f in a["findings"]:
        if f["finding_id"] in ids:
            f["resolved"] = True
    a["status"] = "REMEDIATION"
    touch(a)
    return success_object(serialize.audit(a))


@bp.post("/mga/audits/<auditId>/close")
def close_audit(auditId):
    require_roles("CarrierAuditor")
    a = get_or_404(STORE.carrier_audits, auditId, "CarrierAudit")
    body = get_body()
    outcome = req_enum(body, "outcome", AUDIT_OUTCOMES)
    if a["status"] not in ("FINDINGS_ISSUED", "REMEDIATION"):
        raise_err(ERR_INVALID_STATE, "Only a FINDINGS_ISSUED or REMEDIATION audit can be closed.")
    for f in a["findings"]:
        if f["severity"] in ("MAJOR", "CRITICAL") and not f["resolved"]:
            raise_err(ERR_UNRESOLVED_CRITICAL_FINDINGS, "Unresolved MAJOR/CRITICAL findings bar closure.")
    a["status"] = "CLOSED"
    a["outcome"] = outcome
    touch(a)
    return success_object(serialize.audit(a))


@bp.post("/mga/audits/<auditId>/escalate")
def escalate_audit(auditId):
    require_roles("CarrierAuditor")
    a = get_or_404(STORE.carrier_audits, auditId, "CarrierAudit")
    if a["status"] not in ("FINDINGS_ISSUED", "REMEDIATION"):
        raise_err(ERR_INVALID_STATE, "Only a FINDINGS_ISSUED or REMEDIATION audit can be escalated.")
    if not any(f["severity"] == "CRITICAL" and not f["resolved"] for f in a["findings"]):
        raise_err(ERR_NO_CRITICAL_FINDING, "Escalation requires at least one unresolved CRITICAL finding.")
    a["status"] = "ESCALATED"
    a["outcome"] = "TERMINATION_RECOMMENDED"
    touch(a)
    program = STORE.programs[a["program_id"]]
    if program["status"] == "ACTIVE":
        cascades.suspend_program(program)
    return success_object(serialize.audit(a))
