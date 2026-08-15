"""Royalty report endpoints: intake, validate, accept, void-acceptance."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response
from services import calc

bp = Blueprint("reports", __name__)

OVERLAP_STATUSES = ("SUBMITTED", "VALIDATED", "FLAGGED", "ACCEPTED",
                    "ACCEPTED_WITH_ADJUSTMENT", "AUDIT_REFERRED")


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.err_validation("lines must be a non-empty array")
    has_sub = False
    for l in lines:
        if not isinstance(l, dict):
            raise errors.err_validation("lines entries must be objects")
        for key in l:
            if key not in ("product_label", "units_sold", "gross_sales_cents",
                           "deductions_cents", "is_sublicense_revenue"):
                raise errors.err_validation(f"Undeclared field in lines: {key}")
        if "product_label" not in l or "units_sold" not in l \
                or "gross_sales_cents" not in l or "deductions_cents" not in l:
            raise errors.err_validation(
                "lines entries require product_label, units_sold, gross_sales_cents, deductions_cents")
        if not isinstance(l["product_label"], str):
            raise errors.err_validation("product_label must be a string")
        for f in ("units_sold", "gross_sales_cents", "deductions_cents"):
            if not isinstance(l[f], int) or isinstance(l[f], bool):
                raise errors.err_validation(f"{f} must be an integer")
        if l["units_sold"] < 0:
            raise errors.err_validation("units_sold must be >= 0")
        if l["gross_sales_cents"] < 0:
            raise errors.err_validation("gross_sales_cents must be >= 0")
        if l["deductions_cents"] < 0 or l["deductions_cents"] > l["gross_sales_cents"]:
            raise errors.err_validation(
                "deductions_cents must be >= 0 and <= gross_sales_cents")
        if "is_sublicense_revenue" in l and not isinstance(l["is_sublicense_revenue"], bool):
            raise errors.err_validation("is_sublicense_revenue must be a boolean")
        if l.get("is_sublicense_revenue", False):
            has_sub = True
    return has_sub


@bp.post("/licensing/royalty-reports")
def create_report():
    user_id, role = middleware.require_role("Licensee")
    body = common.get_body()
    common.validate_body(body, [
        ("agreement_id", "string", True),
        ("licensee_id", "string", True),
        ("period_start", "datetime", True),
        ("period_end", "datetime", True),
        ("lines", "array", True),
    ])
    # Tier 3: existence -- path ids left-to-right n/a; body FK references.
    agr = db.agreements.get(body["agreement_id"])
    if agr is None:
        raise errors.err_agreement_not_found()
    lic = db.licensees.get(body["licensee_id"])
    if lic is None:
        raise errors.err_licensee_not_found()
    # Tier 4: ownership
    if body["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    # Tier 5: lines schema
    has_sub = _validate_lines(body["lines"])
    # Tier 6: licensee standing
    if lic["status"] != "ACTIVE":
        raise errors.err_licensee_not_active()
    # Tier 7: agreement standing
    if agr["status"] != "ACTIVE":
        raise errors.err_agreement_not_active()
    # Tier 5/11: window well-formedness and closure
    ps = common.parse_dt(body["period_start"])
    pe = common.parse_dt(body["period_end"])
    if pe <= ps:
        raise errors.err_validation("period_end must be after period_start")
    # Tier 10: half-open overlap with existing non-terminal reports
    for r in db.reports.values():
        if r["agreement_id"] == agr["id"] and r["status"] in OVERLAP_STATUSES:
            rps = common.parse_dt(r["period_start"])
            rpe = common.parse_dt(r["period_end"])
            if ps < rpe and rps < pe:
                raise errors.err_report_period_overlap()
    # Tier 11: period closed
    if pe > common.logical_now():
        raise errors.err_period_not_closed()
    # Tier 12: licensee must match the agreement's contracting licensee
    if body["licensee_id"] != agr["licensee_id"]:
        raise errors.err_validation(
            "licensee_id must equal the agreement's contracting licensee")
    # Tier 12: sublicense lines require an APPROVED grant
    if has_sub:
        approved = any(
            g["agreement_id"] == agr["id"] and g["status"] == "APPROVED"
            for g in db.sublicense_grants.values())
        if not approved:
            raise errors.err_no_approved_sublicense()

    deriv = calc.royalty_base_derivation(agr, body["lines"])
    provisional = calc.royalty_provisional(
        agr, deriv["royalty_base_cents"], deriv["sublicense_net_sales_cents"])

    rep = common.new_resource({
        "agreement_id": body["agreement_id"],
        "licensee_id": body["licensee_id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "lines": [
            {
                "product_label": l["product_label"],
                "units_sold": l["units_sold"],
                "gross_sales_cents": l["gross_sales_cents"],
                "deductions_cents": l["deductions_cents"],
                "is_sublicense_revenue": l.get("is_sublicense_revenue", False),
            }
            for l in body["lines"]
        ],
        "reported_gross_sales_cents": deriv["reported_gross_sales_cents"],
        "reported_net_sales_cents": deriv["reported_net_sales_cents"],
        "royalty_base_cents": deriv["royalty_base_cents"],
        "sublicense_net_sales_cents": deriv["sublicense_net_sales_cents"],
        "provisional_royalty_cents": provisional,
        "benchmark_net_sales_cents": None,
        "adjusted_base_cents": None,
        "final_royalty_cents": None,
        "accepted_at": None,
        "status": "SUBMITTED",
    })
    db.reports[rep["id"]] = rep
    return response.success_object(rep, 201)


@bp.get("/licensing/royalty-reports")
def list_reports():
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee")
    args = common.request.args
    agreement_id = args.get("agreement_id")
    licensee_id = args.get("licensee_id")
    status = args.get("status")
    items = list(db.reports.values())
    if role == "Licensee":
        items = [r for r in items if r["licensee_id"] == user_id]
    if agreement_id is not None:
        items = [r for r in items if r["agreement_id"] == agreement_id]
    if licensee_id is not None:
        items = [r for r in items if r["licensee_id"] == licensee_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/royalty-reports/<rid>")
def get_report(rid):
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee")
    rep = db.reports.get(rid)
    if rep is None:
        raise errors.err_report_not_found()
    if role == "Licensee" and rep["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    return response.success_object(rep)


@bp.post("/licensing/royalty-reports/<rid>/validate")
def validate_report(rid):
    middleware.require_role("LicensingAnalyst")
    rep = db.reports.get(rid)
    if rep is None:
        raise errors.err_report_not_found()
    body = common.get_body()
    common.validate_body(body, [
        ("benchmark_net_sales_cents", "int", True),
    ])
    if body["benchmark_net_sales_cents"] < 0:
        raise errors.err_validation("benchmark_net_sales_cents must be >= 0")
    if rep["status"] != "SUBMITTED":
        raise errors.err_report_invalid_state(
            "Only a SUBMITTED report can be validated")
    agr = db.agreements[rep["agreement_id"]]
    threshold = calc.underreport_threshold(agr, body["benchmark_net_sales_cents"])
    rep["benchmark_net_sales_cents"] = body["benchmark_net_sales_cents"]
    if rep["reported_net_sales_cents"] < threshold:
        rep["status"] = "FLAGGED"
    else:
        rep["status"] = "VALIDATED"
    common.touch(rep)
    return response.success_object(rep)


def _accept_cascade(rep, agr, base_used, final_royalty):
    """Hop 1/1b/2/3 of the acceptance cascade."""
    licensee = db.licensees[agr["licensee_id"]]
    # Hop 1: agreement accumulators
    agr["cumulative_accepted_base_cents"] += base_used
    agr["cumulative_recognized_revenue_cents"] += final_royalty
    agr["undistributed_pool_cents"] += final_royalty
    common.touch(agr)
    # Hop 1b: licensee outstanding balance
    licensee["outstanding_balance_cents"] += final_royalty
    common.touch(licensee)
    # Hop 2 + 3: milestone check on updated cumulative; fee accrual
    calc.milestone_trigger_check(agr)


@bp.post("/licensing/royalty-reports/<rid>/accept")
def accept_report(rid):
    middleware.require_role("LicensingAnalyst")
    rep = db.reports.get(rid)
    if rep is None:
        raise errors.err_report_not_found()
    body = common.get_body()
    # Tier 8 state determines tier 5 conditional-required schema
    if rep["status"] == "FLAGGED":
        common.validate_body(body, [("adjusted_base_cents", "int", True)])
    else:
        common.validate_body(body, [("adjusted_base_cents", "int", False)])
        if "adjusted_base_cents" in body:
            raise errors.err_validation(
                "adjusted_base_cents is forbidden unless the report is FLAGGED")
    # Tier 8: state conformance
    if rep["status"] not in ("VALIDATED", "FLAGGED"):
        raise errors.err_report_invalid_state(
            "Only a VALIDATED or FLAGGED report can be accepted")

    agr = db.agreements[rep["agreement_id"]]
    if rep["status"] == "FLAGGED":
        adjusted = body["adjusted_base_cents"]
        if adjusted < 0:
            raise errors.err_validation("adjusted_base_cents must be >= 0")
        # Tier 13: upward only
        if adjusted <= rep["royalty_base_cents"]:
            raise errors.err_adjustment_not_upward()
        rep["adjusted_base_cents"] = adjusted
        base_used = adjusted
        new_status = "ACCEPTED_WITH_ADJUSTMENT"
    else:
        base_used = rep["royalty_base_cents"]
        new_status = "ACCEPTED"

    rep["final_royalty_cents"] = calc.royalty_final(
        agr, base_used, rep["sublicense_net_sales_cents"])
    rep["accepted_at"] = common.logical_now_str()
    rep["status"] = new_status
    common.touch(rep)

    _accept_cascade(rep, agr, base_used, rep["final_royalty_cents"])
    return response.success_object(rep)


@bp.post("/licensing/royalty-reports/<rid>/void-acceptance")
def void_acceptance(rid):
    middleware.require_role("LicensingAnalyst")
    rep = db.reports.get(rid)
    if rep is None:
        raise errors.err_report_not_found()
    body = common.get_body()
    common.validate_body(body, [("reason", "string", True)])
    # Tier 8: state + no OPEN/DISPUTED findings
    if rep["status"] not in ("ACCEPTED", "ACCEPTED_WITH_ADJUSTMENT"):
        raise errors.err_report_invalid_state(
            "Only an ACCEPTED or ACCEPTED_WITH_ADJUSTMENT report can be voided")
    for f in db.findings.values():
        if f["report_id"] == rep["id"] and f["status"] in ("OPEN", "DISPUTED"):
            raise errors.err_report_invalid_state(
                "Report has an OPEN or DISPUTED audit finding")

    agr = db.agreements[rep["agreement_id"]]
    licensee = db.licensees[agr["licensee_id"]]
    base_used = rep["adjusted_base_cents"] if rep["adjusted_base_cents"] is not None \
        else rep["royalty_base_cents"]
    final = rep["final_royalty_cents"]

    # Compensating reversal: subtract exactly what acceptance added
    agr["cumulative_accepted_base_cents"] -= base_used
    agr["cumulative_recognized_revenue_cents"] -= final
    agr["undistributed_pool_cents"] -= final
    common.touch(agr)
    licensee["outstanding_balance_cents"] -= final
    common.touch(licensee)
    # Milestone revert + fee un-accrual
    calc.milestone_revert_check(agr)

    rep["status"] = "VOIDED"
    common.touch(rep)
    return response.success_object(rep)
