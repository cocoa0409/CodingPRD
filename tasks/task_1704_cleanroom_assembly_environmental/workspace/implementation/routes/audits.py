"""Customer audits and CAPA findings (PRD 3.8)."""

from flask import Blueprint, request

from db import store, new_record, mutate, pub, iso_ms, now, trunc_second
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_AUDIT_NOT_SCHEDULED,
    ERR_AUDIT_WINDOW_NOT_STARTED,
    ERR_AUDIT_NOT_IN_PROGRESS,
    ERR_AUDIT_FINDINGS_OPEN,
    ERR_FINDING_NOT_OPEN,
    ERR_FINDING_NOT_CAPA_SUBMITTED,
)
from middleware import require_role, body, QA, ET
from response import ok, paginate
from services.core import req_string, req_enum, req_iso, touch_room, audit_scope_count

bp = Blueprint("audits", __name__)
READERS = [QA, ET]
SEVERITIES = {"OBSERVATION", "MINOR", "MAJOR", "CRITICAL"}


def load_audit(audit_id):
    audit = store.audits.get(audit_id)
    if audit is None:
        raise ApiError(ERR_NOT_FOUND, 404, "audit %s not found" % audit_id)
    return audit


def load_finding(finding_id):
    finding = store.findings.get(finding_id)
    if finding is None:
        raise ApiError(ERR_NOT_FOUND, 404, "finding %s not found" % finding_id)
    return finding


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/audits")
def create_audit():
    require_role([QA])
    payload = body()
    customer_code = req_string(payload, "customer_code")
    cleanroom_id = payload.get("cleanroom_id")
    if not isinstance(cleanroom_id, str) \
            or store.rooms.get(cleanroom_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleanroom %s not found" % cleanroom_id)
    touch_room(store.rooms[cleanroom_id])
    window_start = req_iso(payload, "window_start")
    window_end = req_iso(payload, "window_end")
    if trunc_second(window_end) <= trunc_second(window_start):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "window_end must be strictly after window_start")
    audit = new_record({
        "customer_code": customer_code,
        "cleanroom_id": cleanroom_id,
        "window_start": iso_ms(window_start),
        "window_end": iso_ms(window_end),
        "status": "SCHEDULED",
    })
    store.audits[audit["id"]] = audit
    return ok(pub(audit), 201)


@bp.get("/cleanroom/audits")
def list_audits():
    require_role(READERS)
    records = list(store.audits.values())
    cleanroom_id = request.args.get("cleanroom_id")
    status = request.args.get("status")
    if cleanroom_id is not None:
        records = [a for a in records if a["cleanroom_id"] == cleanroom_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return paginate(records, request.args)


@bp.get("/cleanroom/audits/<auditId>")
def get_audit(auditId):
    require_role(READERS)
    return ok(pub(load_audit(auditId)))


@bp.post("/cleanroom/audits/<auditId>/open")
def open_audit(auditId):
    require_role([QA])
    audit = load_audit(auditId)
    if audit["status"] != "SCHEDULED":
        raise ApiError(ERR_AUDIT_NOT_SCHEDULED, 409, "audit is not SCHEDULED")
    window_start = req_iso({"window_start": audit["window_start"]}, "window_start")
    if trunc_second(now()) < trunc_second(window_start):
        raise ApiError(ERR_AUDIT_WINDOW_NOT_STARTED, 409,
                       "the audit window has not started")
    audit["status"] = "IN_PROGRESS"
    audit["_scope_record_count"] = audit_scope_count(audit)
    mutate(audit)
    return ok(pub(audit))


@bp.post("/cleanroom/audits/<auditId>/close")
def close_audit(auditId):
    require_role([QA])
    audit = load_audit(auditId)
    if audit["status"] != "IN_PROGRESS":
        raise ApiError(ERR_AUDIT_NOT_IN_PROGRESS, 409,
                       "audit is not IN_PROGRESS")
    findings = [f for f in store.findings.values() if f["audit_id"] == audit["id"]]
    if any(f["status"] != "CAPA_VERIFIED" for f in findings):
        raise ApiError(ERR_AUDIT_FINDINGS_OPEN, 409,
                       "every finding must be CAPA_VERIFIED before close")
    audit["status"] = "CLOSED"
    mutate(audit)
    return ok(pub(audit))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/audits/<auditId>/findings")
def create_finding(auditId):
    require_role([QA])
    audit = load_audit(auditId)
    payload = body()
    finding = new_record({
        "audit_id": audit["id"],
        "severity": req_enum(payload, "severity", SEVERITIES),
        "description": req_string(payload, "description"),
        "status": "OPEN",
    })
    store.findings[finding["id"]] = finding
    return ok(pub(finding), 201)


@bp.get("/cleanroom/audits/<auditId>/findings")
def list_findings(auditId):
    require_role(READERS)
    audit = load_audit(auditId)
    records = [f for f in store.findings.values() if f["audit_id"] == audit["id"]]
    return paginate(records, request.args)


@bp.post("/cleanroom/audit-findings/<findingId>/submit-capa")
def submit_capa(findingId):
    require_role([QA])
    finding = load_finding(findingId)
    if finding["status"] != "OPEN":
        raise ApiError(ERR_FINDING_NOT_OPEN, 409, "finding is not OPEN")
    finding["status"] = "CAPA_SUBMITTED"
    mutate(finding)
    return ok(pub(finding))


@bp.post("/cleanroom/audit-findings/<findingId>/verify-capa")
def verify_capa(findingId):
    require_role([QA])
    finding = load_finding(findingId)
    if finding["status"] != "CAPA_SUBMITTED":
        raise ApiError(ERR_FINDING_NOT_CAPA_SUBMITTED, 409,
                       "finding is not CAPA_SUBMITTED")
    finding["status"] = "CAPA_VERIFIED"
    mutate(finding)
    return ok(pub(finding))
