"""Audit finding endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response
from services import calc

bp = Blueprint("findings", __name__)

EXAMINABLE_STATUSES = ("FLAGGED", "AUDIT_REFERRED", "ACCEPTED",
                       "ACCEPTED_WITH_ADJUSTMENT")


@bp.post("/licensing/audit-findings")
def create_finding():
    user_id, _ = middleware.require_role("LicensingAnalyst")
    body = common.get_body()
    common.validate_body(body, [
        ("audit_id", "string", True),
        ("report_id", "string", True),
        ("finding_type",
         "enum:UNDERREPORTED_BASE,RATE_MISAPPLICATION,DEDUCTION_ABUSE,MISSING_PASS_THROUGH",
         True),
        ("audited_base_cents", "int", True),
    ])
    # Tier 3: body FK existence
    audit = db.audits.get(body["audit_id"])
    if audit is None:
        raise errors.err_audit_not_found()
    rep = db.reports.get(body["report_id"])
    if rep is None:
        raise errors.err_report_not_found()
    if body["audited_base_cents"] < 0:
        raise errors.err_validation("audited_base_cents must be >= 0")
    # Tier 8: audit must be in FIELDWORK
    if audit["status"] != "FIELDWORK":
        raise errors.err_audit_invalid_state(
            "Findings may only be recorded during FIELDWORK")
    # Tier 12: report examinable within scope
    if rep["agreement_id"] != audit["agreement_id"]:
        raise errors.err_report_not_in_audit_scope(
            "Report does not belong to the audit's agreement")
    if rep["status"] not in EXAMINABLE_STATUSES:
        raise errors.err_report_not_in_audit_scope(
            "Report is not in an examinable status")
    rps = common.parse_dt(rep["period_start"])
    rpe = common.parse_dt(rep["period_end"])
    sps = common.parse_dt(audit["scope_period_start"])
    spe = common.parse_dt(audit["scope_period_end"])
    if not (rps <= spe and sps < rpe):
        raise errors.err_report_not_in_audit_scope(
            "Report period does not overlap the audit scope")

    agr = db.agreements[audit["agreement_id"]]
    shortfall = calc.shortfall_calculation(agr, rep, body["audited_base_cents"])

    f = common.new_resource({
        "audit_id": body["audit_id"],
        "report_id": body["report_id"],
        "finding_type": body["finding_type"],
        "audited_base_cents": body["audited_base_cents"],
        "shortfall_cents": shortfall,
        "recorded_by_user_id": user_id,
        "status": "OPEN",
    })
    db.findings[f["id"]] = f
    return response.success_object(f, 201)


def _finding_licensee_id(f):
    rep = db.reports[f["report_id"]]
    return rep["licensee_id"]


@bp.get("/licensing/audit-findings")
def list_findings():
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "Licensee")
    args = common.request.args
    audit_id = args.get("audit_id")
    report_id = args.get("report_id")
    status = args.get("status")
    items = list(db.findings.values())
    if role == "Licensee":
        items = [f for f in items if _finding_licensee_id(f) == user_id]
    if audit_id is not None:
        items = [f for f in items if f["audit_id"] == audit_id]
    if report_id is not None:
        items = [f for f in items if f["report_id"] == report_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/audit-findings/<fid>")
def get_finding(fid):
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "Licensee")
    f = db.findings.get(fid)
    if f is None:
        raise errors.err_finding_not_found()
    if role == "Licensee" and _finding_licensee_id(f) != user_id:
        raise errors.err_not_resource_owner()
    return response.success_object(f)


@bp.post("/licensing/audit-findings/<fid>/resolution")
def resolve_finding(fid):
    user_id, role = middleware.require_role("LicensingAnalyst", "Licensee")
    f = db.findings.get(fid)
    if f is None:
        raise errors.err_finding_not_found()
    body = common.get_body()
    common.validate_body(body, [
        ("resolution", "enum:ACCEPTED,WAIVED", True),
    ])
    resolution = body["resolution"]
    # Role-and-resolution coupling
    if resolution == "ACCEPTED" and role != "Licensee":
        raise errors.err_forbidden_role(
            "Only the owning Licensee may accept a finding")
    if resolution == "WAIVED" and role != "LicensingAnalyst":
        raise errors.err_forbidden_role(
            "Only a LicensingAnalyst may waive a finding")
    # Tier 4: ownership for licensee acceptance
    if role == "Licensee" and _finding_licensee_id(f) != user_id:
        raise errors.err_not_resource_owner()
    # Tier 8: finding must be OPEN
    if f["status"] != "OPEN":
        raise errors.err_finding_not_open()

    f["status"] = resolution
    common.touch(f)
    if resolution == "ACCEPTED":
        rep = db.reports[f["report_id"]]
        agr = db.agreements[rep["agreement_id"]]
        licensee = db.licensees[agr["licensee_id"]]
        licensee["outstanding_balance_cents"] += f["shortfall_cents"]
        common.touch(licensee)
        agr["cumulative_recognized_revenue_cents"] += f["shortfall_cents"]
        agr["undistributed_pool_cents"] += f["shortfall_cents"]
        common.touch(agr)
    return response.success_object(f)


@bp.post("/licensing/audit-findings/<fid>/dispute")
def dispute_finding(fid):
    user_id, role = middleware.require_role("Licensee")
    f = db.findings.get(fid)
    if f is None:
        raise errors.err_finding_not_found()
    body = common.get_body()
    if body:
        raise errors.err_validation("Undeclared fields in request body")
    # Tier 4: ownership
    licensee_id = _finding_licensee_id(f)
    if licensee_id != user_id:
        raise errors.err_not_resource_owner()
    # Tier 8: finding must be OPEN
    if f["status"] != "OPEN":
        raise errors.err_finding_not_open()

    f["status"] = "DISPUTED"
    common.touch(f)

    rep = db.reports[f["report_id"]]
    agr = db.agreements[rep["agreement_id"]]
    dispute = common.new_resource({
        "finding_id": f["id"],
        "agreement_id": agr["id"],
        "licensee_id": agr["licensee_id"],
        "offers": [],
        "settlement_amount_cents": None,
        "awarded_amount_cents": None,
        "ratified_by_user_id": None,
        "status": "OPEN",
    })
    db.disputes[dispute["id"]] = dispute
    return response.success_object(dispute, 201)
