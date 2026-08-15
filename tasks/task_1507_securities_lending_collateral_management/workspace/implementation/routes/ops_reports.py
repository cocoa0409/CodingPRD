"""Ops runs (MTM, month-end close), period closes, clock, and regulatory reports."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import calculations as calc
from services.ops import run_mark_to_market, run_month_end_close
from services.state_machines import _touch
from routes.helpers import (
    get_json_body, require_fields, validate_enum,
    get_or_404, paginate, serialize_common,
)

bp = Blueprint("ops", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]
REPORT_ROLES = ["DeskAdmin", "DeskTrader", "RiskOfficer", "OpsSettler"]
REPORT_TYPES = ["MONTHLY_LOAN_ACTIVITY", "FAILS_AND_BUYINS", "COLLATERAL_SUMMARY"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    result = db.clock.set(body["to_iso8601"])
    return success_object({"current_utc": result})


# ---------------------------------------------------------------------------
# Ops runs
# ---------------------------------------------------------------------------

@bp.route("/api/ops/mark-to-market", methods=["POST"])
def mark_to_market():
    user_id, role = get_auth()
    require_roles(role, ["OpsSettler"])
    result = run_mark_to_market()
    return success_object(result)


@bp.route("/api/ops/month-end-close", methods=["POST"])
def month_end_close():
    user_id, role = get_auth()
    require_roles(role, ["OpsSettler"])
    body = get_json_body()
    require_fields(body, ["period"])
    period = body["period"]
    # Validate YYYY-MM format
    if not isinstance(period, str) or len(period) != 7 or period[4] != "-":
        raise errors.make_error(errors.ERR_VALIDATION, "period must be YYYY-MM format")
    close = run_month_end_close(period)
    return success_object(serialize_common(close), 201)


@bp.route("/api/period-closes/<period_id>", methods=["GET"])
def get_period_close(period_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    close = db.period_closes.get(period_id)
    if close is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, f"PeriodClose not found: {period_id}")
    return success_object(serialize_common(close))


# ---------------------------------------------------------------------------
# Regulatory reports
# ---------------------------------------------------------------------------

@bp.route("/api/regulatory-reports", methods=["POST"])
def create_report():
    user_id, role = get_auth()
    require_roles(role, ["OpsSettler"])
    body = get_json_body()
    require_fields(body, ["period", "report_type"])
    validate_enum(body["report_type"], REPORT_TYPES, "report_type")

    report = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "period": body["period"],
        "report_type": body["report_type"],
        "total_on_loan_value_cents": None,
        "total_fee_income_cents": None,
        "total_rebate_expense_cents": None,
        "fail_count": None,
        "buy_in_count": None,
        "finalized_by_user_id": None,
        "filed_by_user_id": None,
        "status": "DRAFT",
    }
    db.regulatory_reports[report["id"]] = report
    return success_object(serialize_common(report), 201)


@bp.route("/api/regulatory-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    user_id, role = get_auth()
    require_roles(role, REPORT_ROLES)
    report = get_or_404(db.regulatory_reports, report_id, "RegulatoryReport")
    return success_object(serialize_common(report))


@bp.route("/api/regulatory-reports", methods=["GET"])
def list_reports():
    user_id, role = get_auth()
    require_roles(role, REPORT_ROLES)
    items = list(db.regulatory_reports.values())
    period_filter = request.args.get("period")
    status_filter = request.args.get("status")
    if period_filter:
        items = [r for r in items if r["period"] == period_filter]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(r) for r in page], limit, offset, total)


@bp.route("/api/regulatory-reports/<report_id>/finalize", methods=["POST"])
def finalize_report(report_id):
    user_id, role = get_auth()
    require_roles(role, ["OpsSettler"])
    report = get_or_404(db.regulatory_reports, report_id, "RegulatoryReport")
    if report["status"] != "DRAFT":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Report is not DRAFT")

    # Requires PeriodClose
    if report["period"] not in db.period_closes:
        raise errors.make_error(errors.ERR_PERIOD_NOT_CLOSED, f"Period {report['period']} not closed")

    # Compute aggregates
    period = report["period"]

    # total_on_loan_value_cents
    total_on_loan = 0
    for loan in db.loans.values():
        if loan["status"] in ("BOOKED", "RECALLED"):
            calc.recompute_loan_derived(loan)
            total_on_loan += loan["market_value_cents"]
    report["total_on_loan_value_cents"] = total_on_loan

    # total_fee_income_cents
    fee_income = sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e.get("period") == period and e["entry_type"] in ("FEE_ACCRUAL_FINAL", "FEE_TRUE_UP")
    )
    report["total_fee_income_cents"] = fee_income

    # total_rebate_expense_cents (stored negative, express as positive)
    rebate_expense = sum(
        -e["amount_cents"]
        for e in db.ledger_entries.values()
        if e.get("period") == period and e["entry_type"] == "REBATE_ACCRUAL"
    )
    report["total_rebate_expense_cents"] = rebate_expense

    # fail_count
    fail_count = sum(
        1 for r in db.recalls.values()
        if r["status"] in ("FAILED", "BOUGHT_IN") and r.get("_failed_date", "")[:7] == period
    )
    # Also count recalls currently FAILED that entered during period
    # We need to track when they entered FAILED — use _failed_date set during MTM
    report["fail_count"] = fail_count

    # buy_in_count
    buy_in_count = sum(
        1 for r in db.recalls.values()
        if r["status"] == "BOUGHT_IN" and r.get("_bought_in_date", "")[:7] == period
    )
    report["buy_in_count"] = buy_in_count

    report["finalized_by_user_id"] = user_id
    report["status"] = "FINALIZED"
    _touch(report)
    return success_object(serialize_common(report))


@bp.route("/api/regulatory-reports/<report_id>/reopen", methods=["POST"])
def reopen_report(report_id):
    user_id, role = get_auth()
    require_roles(role, ["OpsSettler"])
    report = get_or_404(db.regulatory_reports, report_id, "RegulatoryReport")
    if report["status"] != "FINALIZED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Report is not FINALIZED")

    report["total_on_loan_value_cents"] = None
    report["total_fee_income_cents"] = None
    report["total_rebate_expense_cents"] = None
    report["fail_count"] = None
    report["buy_in_count"] = None
    report["finalized_by_user_id"] = None
    report["status"] = "DRAFT"
    _touch(report)
    return success_object(serialize_common(report))


@bp.route("/api/regulatory-reports/<report_id>/file", methods=["POST"])
def file_report(report_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    report = get_or_404(db.regulatory_reports, report_id, "RegulatoryReport")
    if report["status"] != "FINALIZED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Report is not FINALIZED")

    # SoD: filer != finalizer
    if user_id == report["finalized_by_user_id"]:
        raise errors.make_error(errors.ERR_SOD_VIOLATION, "Filer cannot be the finalizer")

    report["filed_by_user_id"] = user_id
    report["status"] = "FILED"
    _touch(report)
    return success_object(serialize_common(report))
