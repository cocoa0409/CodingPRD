"""Routes: compliance audits and audit findings."""
from flask import Blueprint, request

from store import db
from errors import ApiError
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters
import services
import serializers as ser

bp = Blueprint("audits", __name__, url_prefix="/anesthesia-ops")

AUDITOR = ["ComplianceAuditor"]
AUDIT_READERS = ["GroupAdministrator", "Scheduler", "BillingSpecialist", "ComplianceAuditor"]


def _get_audit(audit_id):
    rec = db.audits.get(audit_id)
    if rec is None:
        raise ApiError("ERR_AUDIT_NOT_FOUND", 404, "Audit not found")
    return rec


def _get_finding(finding_id):
    rec = db.findings.get(finding_id)
    if rec is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", 404, "Finding not found")
    return rec


@bp.post("/audits")
def run_audit():
    auth(AUDITOR)
    body = get_body()
    check_body(body, {"roster_id": {"kind": "str", "req": True}})
    roster = db.rosters.get(body["roster_id"])
    if roster is None:
        raise ApiError("ERR_ROSTER_NOT_FOUND", 404, "Roster not found")
    audit = services.run_audit_scan(roster)
    return ok(ser.audit(audit), 201)


@bp.get("/audits")
def list_audits():
    auth(AUDIT_READERS)
    items = apply_filters(db.audits.values(), request.args, ["roster_id", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.audit(r) for r in page], limit, offset, total)


@bp.get("/audits/<audit_id>")
def get_audit(audit_id):
    auth(AUDIT_READERS)
    return ok(ser.audit(_get_audit(audit_id)))


@bp.post("/audits/<audit_id>/close")
def close_audit(audit_id):
    auth(AUDITOR)
    get_body()
    rec = _get_audit(audit_id)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_NOT_OPEN", 409, "Audit is not OPEN")
    for f in db.findings.values():
        if f["audit_id"] == rec["id"] and f["status"] == "OPEN":
            raise ApiError("ERR_UNRESOLVED_FINDINGS", 409,
                           "Audit still has OPEN findings")
    rec["status"] = "CLOSED"
    db.bump(rec)
    return ok(ser.audit(rec))


@bp.get("/findings")
def list_findings():
    auth(AUDIT_READERS)
    items = apply_filters(db.findings.values(), request.args,
                          ["audit_id", "case_id", "assignment_id", "finding_type", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.finding(r) for r in page], limit, offset, total)


@bp.get("/findings/<finding_id>")
def get_finding(finding_id):
    auth(AUDIT_READERS)
    return ok(ser.finding(_get_finding(finding_id)))


def _settle_finding(finding_id, new_status):
    auth(AUDITOR)
    body = get_body()
    check_body(body, {
        "resolution_note": {"kind": "str", "req": False},
        "dismissal_reason": {"kind": "str", "req": False},
    })
    rec = _get_finding(finding_id)
    audit = db.audits[rec["audit_id"]]
    if audit["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_NOT_OPEN", 409, "Parent audit is not OPEN")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_NOT_OPEN", 409, "Finding is not OPEN")
    rec["status"] = new_status
    note = body.get("resolution_note")
    if note is None:
        note = body.get("dismissal_reason")
    if note is not None:
        rec["resolution_note"] = note
    db.bump(rec)
    return ok(ser.finding(rec))


@bp.post("/findings/<finding_id>/resolve")
def resolve_finding(finding_id):
    return _settle_finding(finding_id, "RESOLVED")


@bp.post("/findings/<finding_id>/dismiss")
def dismiss_finding(finding_id):
    return _settle_finding(finding_id, "DISMISSED")
