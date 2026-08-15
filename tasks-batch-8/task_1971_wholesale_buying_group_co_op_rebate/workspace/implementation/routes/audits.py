"""VolumeAudit lifecycle and retroactive adjudication (PRD §3.5)."""

from flask import Blueprint, request

import db
from db import store, new_entity, touch, public
from errors import err_not_found, err_state, err_reference, err_not_owner
from middleware import require_roles, body_json, req_str, req_int
from response import success_object, success_list, parse_pagination, paginate
from services import lifecycle

bp = Blueprint("audits", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor", "MemberRep")


def get_audit_or_404(audit_id):
    audit = store.audits.get(audit_id)
    if audit is None:
        raise err_not_found("VolumeAudit not found")
    return audit


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _owning_member_id(audit):
    enr = store.enrollments[audit["enrollment_id"]]
    return enr["member_id"]


@bp.route("/coop/volume-audits", methods=["POST"])
@require_roles("ProgramAuditor")
def create_audit(uid, role):
    body = body_json(required=True)
    report_id = req_str(body, "purchase_report_id")
    report = store.reports.get(report_id)
    if report is None:
        raise err_reference("purchase_report_id does not resolve to an existing PurchaseReport")
    # Audits are opened against a SUBMITTED report; SUPERSEDED rows are dead.
    if report["status"] != "SUBMITTED":
        raise err_state("An audit can only be opened against a SUBMITTED report")
    audit = new_entity()
    audit.update({
        "enrollment_id": report["enrollment_id"],
        "purchase_report_id": report["id"],
        "opened_quarter_index": db.get_coop()["current_quarter_index"],
        "resolved_quarter_index": None,
        "finding_severity": None,
        "audited_qty": None,
        "audited_cents": None,
        "status": "OPEN",
    })
    store.audits[audit["id"]] = audit
    return success_object(public(audit), code=201)


@bp.route("/coop/volume-audits/<audit_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_audit(uid, role, audit_id):
    return success_object(public(get_audit_or_404(audit_id)), code=200)


@bp.route("/coop/volume-audits", methods=["GET"])
@require_roles(*READ_ROLES)
def list_audits(uid, role):
    limit, offset = parse_pagination()
    items = list(store.audits.values())
    enrollment_id = _arg("enrollment_id")
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    status = _arg("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    severity = _arg("finding_severity")
    if severity is not None:
        items = [a for a in items if a["finding_severity"] == severity]
    page, total = paginate(items, limit, offset)
    return success_list([public(a) for a in page], limit, offset, total)


def _transition(audit_id, expected, new_status):
    audit = get_audit_or_404(audit_id)
    if audit["status"] != expected:
        raise err_state("Audit must be %s for this transition" % expected)
    audit["status"] = new_status
    touch(audit)
    return success_object(public(audit), code=200)


@bp.route("/coop/volume-audits/<audit_id>/begin_fieldwork", methods=["POST"])
@require_roles("ProgramAuditor")
def begin_fieldwork(uid, role, audit_id):
    return _transition(audit_id, "OPEN", "FIELDWORK")


@bp.route("/coop/volume-audits/<audit_id>/issue_findings", methods=["POST"])
@require_roles("ProgramAuditor")
def issue_findings(uid, role, audit_id):
    return _transition(audit_id, "FIELDWORK", "FINDINGS_ISSUED")


@bp.route("/coop/volume-audits/<audit_id>/accept_findings", methods=["POST"])
@require_roles("MemberRep")
def accept_findings(uid, role, audit_id):
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "FINDINGS_ISSUED":
        raise err_state("Audit must be FINDINGS_ISSUED to accept findings")
    if _owning_member_id(audit) != uid:
        raise err_not_owner("MemberRep may only accept findings for their own member")
    audit["status"] = "ACCEPTED"
    touch(audit)
    return success_object(public(audit), code=200)


@bp.route("/coop/volume-audits/<audit_id>/appeal", methods=["POST"])
@require_roles("MemberRep")
def appeal(uid, role, audit_id):
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "FINDINGS_ISSUED":
        raise err_state("Audit must be FINDINGS_ISSUED to appeal")
    if _owning_member_id(audit) != uid:
        raise err_not_owner("MemberRep may only appeal findings for their own member")
    audit["status"] = "APPEALED"
    touch(audit)
    return success_object(public(audit), code=200)


@bp.route("/coop/volume-audits/<audit_id>/reopen_fieldwork", methods=["POST"])
@require_roles("ProgramAuditor")
def reopen_fieldwork(uid, role, audit_id):
    return _transition(audit_id, "APPEALED", "FIELDWORK")


@bp.route("/coop/volume-audits/<audit_id>/resolve", methods=["POST"])
@require_roles("ProgramAuditor")
def resolve(uid, role, audit_id):
    audit = get_audit_or_404(audit_id)
    body = body_json(required=True)
    audited_qty = req_int(body, "audited_qty", minimum=0)
    audited_cents = req_int(body, "audited_cents", minimum=0)
    if audit["status"] != "ACCEPTED":
        raise err_state("Only an ACCEPTED audit can be resolved")
    lifecycle.resolve_audit(audit, audited_qty, audited_cents)
    return success_object(public(audit), code=200)
