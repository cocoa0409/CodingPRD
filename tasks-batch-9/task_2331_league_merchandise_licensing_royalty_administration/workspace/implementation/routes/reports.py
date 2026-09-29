"""Quarterly royalty reports: creation, correction, filing and review (PRD 3.7)."""

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_LICENSEE,
                        ROLE_MANAGER, guard, paginate, pagination)
from services import calc, domain
from services import retailers as R

bp = Blueprint("reports", __name__)

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_LICENSEE]

COMPUTED_MONEY = ("net_regular_total_cents", "closeout_eligible_total_cents",
                  "applied_tier_rate_bps", "royalty_due_cents",
                  "recoupment_applied_cents", "cash_due_pre_fee_cents", "late_days",
                  "late_filing_interest_cents", "admin_fee_cents", "total_payable_cents")


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def find_report(report_id):
    row = S.reports.get(report_id)
    if row is None:
        raise ApiError("ERR_REPORT_NOT_FOUND")
    return row


def effective_royalty(report):
    adjusted = report.get("adjusted_royalty_due_cents")
    return adjusted if adjusted is not None else report["royalty_due_cents"]


# --------------------------------------------------------------------------- #
# line validation                                                             #
# --------------------------------------------------------------------------- #

def _resolve_line_authorizations(raw):
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        auth_id = entry.get("retailer_authorization_id")
        if isinstance(auth_id, str) and auth_id not in S.authorizations:
            raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")


def _validate_lines(body):
    raw = V.req_list(body, "channel_lines", 1, 6)
    lines = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            _bad("channel_lines entries must be objects.")
        channel_class = V.req_enum(entry, "channel_class", K.LINE_CHANNEL_CLASSES)
        if channel_class in seen:
            _bad("channel_lines entries must carry distinct channel_class values.")
        seen.add(channel_class)
        auth_id = V.req_string(entry, "retailer_authorization_id")
        gross = V.req_cents(entry, "gross_sales_cents")
        units = V.req_units(entry, "units")
        closeout = V.req_cents(entry, "closeout_sales_cents")
        deductions = V.req_cents(entry, "deductions_cents")
        lines.append({
            "channel_class": channel_class,
            "retailer_authorization_id": auth_id,
            "gross_sales_cents": gross,
            "units": units,
            "closeout_sales_cents": closeout,
            "deductions_cents": deductions,
        })
    return lines


def _check_line_retailers(lines, agreement):
    """Rule 23."""
    for line in calc.ordered_lines(lines):
        auth = R.find_auth(line["retailer_authorization_id"])
        if auth["licensee_id"] != agreement["licensee_id"] or \
                auth["channel_class"] != line["channel_class"]:
            raise ApiError("ERR_CHANNEL_LINE_RETAILER_MISMATCH")


def _check_line_usability(lines, period_quarter):
    """Rule 24."""
    for line in calc.ordered_lines(lines):
        auth = R.find_auth(line["retailer_authorization_id"])
        if not R.usable_for_period(auth, period_quarter):
            raise ApiError("ERR_CHANNEL_NOT_AUTHORIZED")


def _check_line_fiscal(lines, category):
    """Rules 29, 30 and 31 in that order, each in ascending channel order."""
    ordered = calc.ordered_lines(lines)
    for line in ordered:
        limit = calc.apply_rate_floor(line["gross_sales_cents"],
                                     category["deduction_hard_limit_bps"])
        if line["deductions_cents"] > limit:
            raise ApiError("ERR_DEDUCTION_LIMIT_EXCEEDED")
    for line in ordered:
        limit = calc.apply_rate_floor(line["gross_sales_cents"],
                                     category["closeout_hard_limit_bps"])
        if line["closeout_sales_cents"] > line["gross_sales_cents"] or \
                line["closeout_sales_cents"] > limit:
            raise ApiError("ERR_CLOSEOUT_LIMIT_EXCEEDED")
    for line in ordered:
        auth = R.find_auth(line["retailer_authorization_id"])
        if line["closeout_sales_cents"] > 0 and not auth["closeout_allowed"]:
            raise ApiError("ERR_CLOSEOUT_NOT_PERMITTED")
        if line["channel_class"] == "OFF_PRICE" and line["closeout_sales_cents"] <= 0:
            raise ApiError("ERR_CLOSEOUT_NOT_PERMITTED")


# --------------------------------------------------------------------------- #
# royalty and waterfall                                                       #
# --------------------------------------------------------------------------- #

def late_days_for(period_quarter, as_of_date):
    deadline = db.filing_deadline_date(period_quarter)
    delta = (as_of_date - deadline).days
    return delta if delta > 0 else 0


def apply_waterfall(report, agreement, royalty_cents, posture, late_days):
    result = calc.payable_waterfall(royalty_cents,
                                    agreement["unrecouped_advance_cents"],
                                    posture, late_days)
    report.update(result)
    return result


# --------------------------------------------------------------------------- #
# creation, reads and correction                                              #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/royalty-reports")
def create_report():
    ctx = guard([ROLE_LICENSEE, ROLE_FINANCE])
    body = ctx.body

    agreement_id = body.get("agreement_id")
    if agreement_id is not None and agreement_id not in S.agreements:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    if agreement_id is None:
        _bad("agreement_id is required.")
    agreement = S.agreements[agreement_id]
    mw.scope_agreement(ctx, agreement)
    _resolve_line_authorizations(body.get("channel_lines"))

    V.req_string(body, "agreement_id")
    period_quarter = V.req_quarter(body, "period_quarter")
    lines = _validate_lines(body)
    expected = V.req_int(body, "expected_agreement_version")

    if expected != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")

    category = domain.category_of(agreement)
    _check_line_retailers(lines, agreement)
    _check_line_usability(lines, period_quarter)

    start_quarter = db.quarter_of_iso(agreement["term_start_date"])
    end_quarter = db.quarter_of_iso(agreement["term_end_date"])
    if db.elapsed_quarters(start_quarter, period_quarter) < 0 or \
            db.elapsed_quarters(period_quarter, end_quarter) < 0:
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM")

    _check_line_fiscal(lines, category)

    for other in domain.reports_of(agreement_id):
        if other["period_quarter"] == period_quarter and other["status"] != "RETURNED":
            raise ApiError("ERR_DUPLICATE_REPORT_PERIOD")

    row = db.base_row()
    row.update({
        "agreement_id": agreement_id,
        "period_quarter": period_quarter,
        "channel_lines": lines,
        "status": "DRAFT",
        "net_regular_total_cents": 0,
        "closeout_eligible_total_cents": 0,
        "applied_tier_rate_bps": 0,
        "royalty_due_cents": 0,
        "recoupment_applied_cents": 0,
        "cash_due_pre_fee_cents": 0,
        "late_days": 0,
        "late_filing_interest_cents": 0,
        "admin_fee_cents": 0,
        "total_payable_cents": 0,
        "filed_at": None,
        "return_count": 0,
        "return_reason": None,
        "accepted_by_user_id": None,
        "accepted_at": None,
        "adjusted_royalty_due_cents": None,
        "audit_engagement_id": None,
        "distribution_run_id": None,
    })
    S.reports[row["id"]] = row
    touch(agreement)
    return response.created(serializers.dump("RoyaltyReport", row))


@bp.get("/licensing/royalty-reports")
def list_reports():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    agreement_id = mw.filter_str("agreement_id")
    engagement_id = mw.filter_str("audit_engagement_id")
    run_id = mw.filter_str("distribution_run_id")
    period_quarter = mw.filter_str("period_quarter")
    status = mw.filter_enum("status", K.REPORT_STATUSES)

    rows = list(S.reports.values())
    if ctx.role == ROLE_LICENSEE:
        own = {a["id"] for a in domain.agreements_of(ctx.uid)}
        rows = [r for r in rows if r["agreement_id"] in own]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if engagement_id is not None:
        rows = [r for r in rows if r["audit_engagement_id"] == engagement_id]
    if run_id is not None:
        rows = [r for r in rows if r["distribution_run_id"] == run_id]
    if period_quarter is not None:
        rows = [r for r in rows if r["period_quarter"] == period_quarter]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("RoyaltyReport", page),
                            limit, offset, total)


@bp.get("/licensing/royalty-reports/<report_id>")
def get_report(report_id):
    ctx = guard(READ_ROLES)
    report = find_report(report_id)
    mw.scope_agreement(ctx, S.agreements[report["agreement_id"]])
    return response.ok(serializers.dump("RoyaltyReport", report))


@bp.patch("/licensing/royalty-reports/<report_id>")
def patch_report(report_id):
    ctx = guard([ROLE_LICENSEE])
    report = find_report(report_id)
    agreement = S.agreements[report["agreement_id"]]
    mw.scope_agreement(ctx, agreement)
    body = ctx.body

    _resolve_line_authorizations(body.get("channel_lines"))
    lines = _validate_lines(body)

    if report["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE")

    category = domain.category_of(agreement)
    _check_line_retailers(lines, agreement)
    _check_line_fiscal(lines, category)

    report["channel_lines"] = lines
    for field in COMPUTED_MONEY:
        report[field] = 0
    touch(report)
    return response.ok(serializers.dump("RoyaltyReport", report))


# --------------------------------------------------------------------------- #
# filing                                                                      #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/royalty-reports/<report_id>/file")
def file_report(report_id):
    ctx = guard([ROLE_LICENSEE])
    report = find_report(report_id)
    agreement = S.agreements[report["agreement_id"]]
    mw.scope_agreement(ctx, agreement)

    origin = report["status"]
    if origin not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE")
    if agreement["contract_status"] not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE", "The governing agreement is not accountable.")

    _check_line_usability(report["channel_lines"], report["period_quarter"])

    quarter_end = db.quarter_end_date(report["period_quarter"])
    if db.clock_date() < quarter_end:
        raise ApiError("ERR_PERIOD_NOT_ENDED")

    category = domain.category_of(agreement)
    rated = calc.compute_royalty(report["channel_lines"], category)
    report.update(rated)
    late_days = late_days_for(report["period_quarter"], db.clock_date())
    apply_waterfall(report, agreement, rated["royalty_due_cents"],
                    agreement["compliance_posture"], late_days)

    report["status"] = "FILED"
    report["filed_at"] = db.now_iso()
    if origin == "RETURNED":
        report["return_reason"] = None
    touch(report)
    return response.ok(serializers.dump("RoyaltyReport", report))


# --------------------------------------------------------------------------- #
# acceptance and return                                                       #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/royalty-reports/<report_id>/review-decisions")
def report_review(report_id):
    ctx = guard([ROLE_FINANCE])
    report = find_report(report_id)
    agreement = S.agreements[report["agreement_id"]]
    body = ctx.body
    decision = V.req_enum(body, "decision", ("RETURN", "ACCEPT"))
    reason = V.opt_string(body, "reason")
    if decision == "RETURN" and not reason:
        _bad("reason is required when returning a report.")

    if report["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE")
    if decision == "ACCEPT" and \
            agreement["contract_status"] not in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE", "The governing agreement is not accountable.")
    if agreement["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_POSTURE_FROZEN")

    if decision == "RETURN":
        report["status"] = "RETURNED"
        report["return_reason"] = reason
        report["return_count"] += 1
        touch(report)
        domain.refresh_risk_index(domain.licensee_of(agreement))
        return response.ok(serializers.dump("RoyaltyReport", report))

    for run in S.runs.values():
        if run["period_quarter"] == report["period_quarter"] and \
                run["status"] == "DISTRIBUTED":
            raise ApiError("ERR_DISTRIBUTION_ALREADY_CLOSED")

    royalty = report["royalty_due_cents"]
    result = apply_waterfall(report, agreement, royalty,
                             agreement["compliance_posture"], report["late_days"])
    report["status"] = "ACCEPTED"
    report["accepted_by_user_id"] = ctx.uid
    report["accepted_at"] = db.now_iso()

    agreement["unrecouped_advance_cents"] -= result["recoupment_applied_cents"]
    agreement["recouped_advance_cents"] += result["recoupment_applied_cents"]
    agreement["cumulative_royalty_cents"] += royalty
    touch(agreement)

    if agreement["central_licensing_flag"]:
        for run in S.runs.values():
            if run["period_quarter"] == report["period_quarter"] and \
                    run["status"] == "OPEN":
                report["distribution_run_id"] = run["id"]
                run["projected_pool_cents"] += royalty
                run["report_count"] += 1
                touch(run)
                break

    touch(report)
    return response.ok(serializers.dump("RoyaltyReport", report))
