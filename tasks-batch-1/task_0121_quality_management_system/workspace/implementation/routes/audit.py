"""Audit and AuditFinding routes (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from common import (parse_iso, require_enum, require_fields, require_string,
                    stamp_create, touch)
from db import db
from errors import (ERR_AUDIT_HAS_OPEN_FINDINGS, ERR_AUDITOR_DOUBLE_BOOKED,
                    ERR_FINDING_NCR_OPEN, ERR_FINDING_REQUIRES_NCR,
                    ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, err)
from middleware import (ROLE_AUDITOR, ROLE_QUALITY_ENGINEER,
                        ROLE_QUALITY_MANAGER, authenticate, require_role)
from response import list_success, success
from services.helpers import get_or_404, paginate, paginate_args
from services.serializers import audit_finding_out, audit_out

bp = Blueprint("audit", __name__)

AUDIT_ACTIONS = {"START", "CLOSE"}
FINDING_GRADES = {"MAJOR", "MINOR", "OBSERVATION"}
FINDING_ACTIONS = {"CLOSE", "VOID"}
AUDITOR_BUFFER = timedelta(hours=24)


@bp.route("/audits", methods=["POST"])
def create_audit():
    auth = authenticate()
    require_role(auth, {ROLE_AUDITOR})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4): lead_auditor_id must resolve to an AUDITOR.
    lead_auditor_id = body.get("lead_auditor_id")
    if lead_auditor_id is not None:
        person = db.personnel.get(lead_auditor_id)
        if person is None or person["role"] != "AUDITOR":
            raise err(ERR_FK_NOT_FOUND, "lead_auditor_id must resolve to an AUDITOR")

    # Well-formedness (priority 5).
    require_fields(body, ["title", "lead_auditor_id", "scheduled_from", "scheduled_to"])
    require_string(body["title"], "title")
    sched_from = parse_iso(body["scheduled_from"])
    sched_to = parse_iso(body["scheduled_to"])

    clause_scope = body.get("clause_scope")

    rec = {
        "title": body["title"],
        "lead_auditor_id": lead_auditor_id,
        "scheduled_from": body["scheduled_from"],
        "scheduled_to": body["scheduled_to"],
        "scheduled_from_dt": sched_from,
        "scheduled_to_dt": sched_to,
        "clause_scope": clause_scope,
        "status": "PLANNED",
        "open_finding_count": 0,
    }
    stamp_create(rec)
    db.audits[rec["id"]] = rec
    return success(audit_out(rec), status=201)


@bp.route("/audits/<rid>", methods=["GET"])
def get_audit(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_AUDITOR})
    rec = get_or_404(db.audits, rid)
    return success(audit_out(rec))


@bp.route("/audits/<rid>/transition", methods=["POST"])
def transition_audit(rid):
    auth = authenticate()
    require_role(auth, {ROLE_AUDITOR})
    rec = get_or_404(db.audits, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["action"])
    action = body["action"]
    require_enum(action, AUDIT_ACTIONS, "action")

    if action == "START":
        if rec["status"] != "PLANNED":
            raise err(ERR_INVALID_STATE, "START requires PLANNED")
        # Ownership (priority 7).
        if auth.user_id != rec["lead_auditor_id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "Only the lead auditor may start")
        # Double-booking buffered-closed check (PRD 3.8).
        for other in db.audits.values():
            if other["id"] == rec["id"]:
                continue
            if other["lead_auditor_id"] != rec["lead_auditor_id"]:
                continue
            if other["status"] not in {"PLANNED", "IN_PROGRESS"}:
                continue
            # Reject iff this.from <= other.to + 24h AND other.from <= this.to + 24h.
            if (rec["scheduled_from_dt"] <= other["scheduled_to_dt"] + AUDITOR_BUFFER
                    and other["scheduled_from_dt"] <= rec["scheduled_to_dt"] + AUDITOR_BUFFER):
                raise err(ERR_AUDITOR_DOUBLE_BOOKED, "Lead auditor is double-booked")
        rec["status"] = "IN_PROGRESS"
        touch(rec)
        return success(audit_out(rec))

    # CLOSE
    if rec["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE, "CLOSE requires IN_PROGRESS")
    if auth.user_id != rec["lead_auditor_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Only the lead auditor may close")
    if rec["open_finding_count"] != 0:
        raise err(ERR_AUDIT_HAS_OPEN_FINDINGS, "Audit has open findings")
    rec["status"] = "CLOSED"
    touch(rec)
    return success(audit_out(rec))


@bp.route("/audits/<rid>/findings", methods=["POST"])
def create_finding(rid):
    auth = authenticate()
    require_role(auth, {ROLE_AUDITOR})
    audit = get_or_404(db.audits, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["clause", "grade", "description"])
    require_string(body["clause"], "clause")
    require_enum(body["grade"], FINDING_GRADES, "grade")
    require_string(body["description"], "description")

    rec = {
        "audit_id": audit["id"],
        "clause": body["clause"],
        "grade": body["grade"],
        "description": body["description"],
        "status": "OPEN",
        "raised_ncr_id": None,
    }
    stamp_create(rec)
    db.audit_findings[rec["id"]] = rec

    # Increment parent audit open_finding_count (PRD 3.8).
    audit["open_finding_count"] += 1
    touch(audit)

    return success(audit_finding_out(rec), status=201)


@bp.route("/audit-findings/<rid>", methods=["GET"])
def get_finding(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_AUDITOR, ROLE_QUALITY_ENGINEER})
    rec = get_or_404(db.audit_findings, rid)
    return success(audit_finding_out(rec))


@bp.route("/audits/<rid>/findings", methods=["GET"])
def list_findings(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_AUDITOR})
    get_or_404(db.audits, rid)
    limit, offset = paginate_args()
    matches = [f for f in db.audit_findings.values() if f["audit_id"] == rid]
    page, total = paginate(matches, limit, offset)
    return list_success([audit_finding_out(f) for f in page], limit, offset, total)


@bp.route("/audit-findings/<rid>/transition", methods=["POST"])
def transition_finding(rid):
    auth = authenticate()
    require_role(auth, {ROLE_AUDITOR})
    rec = get_or_404(db.audit_findings, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["action"])
    action = body["action"]
    require_enum(action, FINDING_ACTIONS, "action")

    audit = db.audits.get(rec["audit_id"])

    if action == "CLOSE":
        if rec["status"] == "NCR_RAISED":
            # Requires the escalated NCR to be CLOSED (PRD 3.8).
            ncr = db.nonconformance_reports.get(rec["raised_ncr_id"])
            if ncr is None or ncr["status"] != "CLOSED":
                raise err(ERR_FINDING_NCR_OPEN, "Escalated NCR is not CLOSED")
            rec["status"] = "CLOSED"
            touch(rec)
            _decrement_open_findings(audit)
            return success(audit_finding_out(rec))
        if rec["status"] == "OPEN":
            # Only OBSERVATION may close directly from OPEN (PRD 3.8).
            if rec["grade"] != "OBSERVATION":
                raise err(ERR_FINDING_REQUIRES_NCR,
                          "Non-observation finding requires an NCR before closing")
            rec["status"] = "CLOSED"
            touch(rec)
            _decrement_open_findings(audit)
            return success(audit_finding_out(rec))
        raise err(ERR_INVALID_STATE, "CLOSE not defined from current state")

    # VOID
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "VOID requires OPEN")
    rec["status"] = "VOID"
    touch(rec)
    _decrement_open_findings(audit)
    return success(audit_finding_out(rec))


def _decrement_open_findings(audit):
    if audit is not None:
        audit["open_finding_count"] -= 1
        touch(audit)
