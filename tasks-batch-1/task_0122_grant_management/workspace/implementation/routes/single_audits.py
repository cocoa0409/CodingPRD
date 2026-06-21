"""SingleAudit and AuditFinding endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("single_audits", __name__)

SINGLE_AUDIT_THRESHOLD_CENTS = 75000000   # $750,000 inclusive boundary
SEVERITIES = {"DEFICIENCY", "SIGNIFICANT_DEFICIENCY", "MATERIAL_WEAKNESS"}
AUDIT_READ_ROLES = ("Auditor", "AgencyOfficer")


def _serialize_audit(a):
    return c.serialize(a)


def _serialize_finding(f):
    return c.serialize(f)


def _load_audit(audit_id):
    a = db.single_audits.get(audit_id)
    if a is None:
        raise errors.not_found("Single audit not found.")
    return a


@bp.route("/single-audits", methods=["POST"])
@require_roles("Auditor")
def create_audit(user_id, role):
    body = c.get_body()

    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        if award_id not in db.awards:
            raise errors.not_found("Award not found.")

        fiscal_year = c.require_int(body, "fiscal_year", minimum=2000)
        federal_expenditures_cents = c.require_int(body, "federal_expenditures_cents", minimum=0)

        audit_required = federal_expenditures_cents >= SINGLE_AUDIT_THRESHOLD_CENTS

        record = {
            "award_id": award_id,
            "fiscal_year": fiscal_year,
            "federal_expenditures_cents": federal_expenditures_cents,
            "audit_required": audit_required,
            "status": "OPEN",
        }
        db.stamp_create(record)
        db.single_audits[record["id"]] = record
        return success(_serialize_audit(record), status=201)


@bp.route("/single-audits", methods=["GET"])
@require_roles(*AUDIT_READ_ROLES)
def list_audits(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.single_audits.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize_audit(r) for r in page], status=200, pagination=pagination)


@bp.route("/single-audits/<audit_id>", methods=["GET"])
@require_roles(*AUDIT_READ_ROLES)
def get_audit(audit_id, user_id, role):
    with db.LOCK:
        return success(_serialize_audit(_load_audit(audit_id)), status=200)


@bp.route("/single-audits/<audit_id>/submit", methods=["POST"])
@require_roles("Auditor")
def submit_audit(audit_id, user_id, role):
    with db.LOCK:
        audit = _load_audit(audit_id)
        # Submit defined only from OPEN with audit_required == true (PRD §3.8).
        if audit["status"] != "OPEN" or not audit["audit_required"]:
            raise errors.invalid_state("Only an OPEN required audit may be submitted.")
        audit["status"] = "SUBMITTED"
        db.touch(audit)
        return success(_serialize_audit(audit), status=200)


@bp.route("/single-audits/<audit_id>/resolve", methods=["POST"])
@require_roles("Auditor")
def resolve_audit(audit_id, user_id, role):
    with db.LOCK:
        audit = _load_audit(audit_id)
        status = audit["status"]
        if status == "SUBMITTED":
            # Resolve from SUBMITTED requires all MATERIAL_WEAKNESS findings RESOLVED.
            for f in db.audit_findings.values():
                if (f["single_audit_id"] == audit["id"]
                        and f["severity"] == "MATERIAL_WEAKNESS"
                        and f["status"] != "RESOLVED"):
                    raise errors.invalid_state(
                        "All MATERIAL_WEAKNESS findings must be RESOLVED before resolving the audit."
                    )
        elif status == "OPEN":
            # Direct resolve from OPEN only when not required (PRD §3.8).
            if audit["audit_required"]:
                raise errors.invalid_state("A required OPEN audit must be submitted before resolution.")
        else:
            raise errors.invalid_state("Audit is in a state from which resolution is not defined.")
        audit["status"] = "RESOLVED"
        db.touch(audit)
        return success(_serialize_audit(audit), status=200)


@bp.route("/single-audits/<audit_id>/findings", methods=["POST"])
@require_roles("Auditor")
def create_finding(audit_id, user_id, role):
    body = c.get_body()
    with db.LOCK:
        _load_audit(audit_id)
        severity = c.require_enum(body, "severity", SEVERITIES)
        questioned_cost_cents = c.optional_int(body, "questioned_cost_cents", 0, minimum=0)
        record = {
            "single_audit_id": audit_id,
            "severity": severity,
            "questioned_cost_cents": questioned_cost_cents,
            "status": "OPEN",
        }
        db.stamp_create(record)
        db.audit_findings[record["id"]] = record
        return success(_serialize_finding(record), status=201)


@bp.route("/single-audits/<audit_id>/findings", methods=["GET"])
@require_roles(*AUDIT_READ_ROLES)
def list_findings(audit_id, user_id, role):
    limit, offset = c.parse_pagination()
    with db.LOCK:
        _load_audit(audit_id)
        records = [f for f in db.audit_findings.values() if f["single_audit_id"] == audit_id]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize_finding(r) for r in page], status=200, pagination=pagination)


@bp.route("/audit-findings/<finding_id>/resolve", methods=["POST"])
@require_roles("Auditor")
def resolve_finding(finding_id, user_id, role):
    with db.LOCK:
        finding = db.audit_findings.get(finding_id)
        if finding is None:
            raise errors.not_found("Audit finding not found.")
        if finding["status"] != "OPEN":
            raise errors.invalid_state("Only an OPEN finding may be resolved.")
        finding["status"] = "RESOLVED"
        db.touch(finding)
        return success(_serialize_finding(finding), status=200)
