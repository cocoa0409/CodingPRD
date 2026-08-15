"""Subscription lifecycle endpoints (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_KYC_REJECTED,
    ERR_CLASS_CLOSED, ERR_BELOW_MIN_INVESTMENT, ERR_FUNDING_DEADLINE_PASSED,
    ERR_INVALID_AMOUNT, ERR_NO_OPEN_NAV_PERIOD, ERR_SERIES_MISMATCH,
    ERR_STALE_VERSION,
)
from middleware import require_roles, check_investor_owns
from response import success_object, success_list
from services.core import (
    stamp_new, touch, serialize, paginate, filter_by,
    get_fund, get_share_class, get_investor, get_subscription, get_series,
    get_nav_period, child_of, open_kyc_case, recompute_unfunded,
    class_nav_per_share, current_open_series, mint_series,
    compute_locked_until, base_fee_bps, reset_period_accumulators,
)
from util import CLOCK, round_half_up_int
from validate import (
    get_body, req_str, req_int, req_datetime, opt_int, opt_str,
)

bp = Blueprint("subscriptions", __name__)

SUB_READERS = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager", "Investor")
SUB_LISTERS = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager")


def _load_sub_under_fund(fund_id, sub_id):
    fund = get_fund(fund_id)
    sub = get_subscription(sub_id)
    child_of(sub, "_fund_id", fund["id"])
    return fund, sub


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/subscriptions")
def create_subscription(fund_id):
    caller = require_roles("Investor", "TransferAgent", "FundAdmin")
    fund = get_fund(fund_id)
    body = get_body()
    investor_id = req_str(body, "investor_id")
    share_class_id = req_str(body, "share_class_id")
    commitment = req_int(body, "commitment_amount_cents")
    funding_deadline = req_datetime(body, "funding_deadline_utc")
    check_investor_owns(caller, investor_id)

    investor = get_investor(investor_id)
    share_class = db["share_classes"].get(share_class_id)
    if share_class is None or share_class["fund_id"] != fund["id"]:
        raise_error(ERR_NOT_FOUND, "share_class_id does not belong to this fund")

    # Business rules (create-time): minimum investment (12) then class open (13).
    if commitment < share_class["min_initial_investment_cents"]:
        raise_error(ERR_BELOW_MIN_INVESTMENT,
                    "commitment_amount_cents below min_initial_investment_cents")
    if not share_class["is_open_for_subscription"]:
        raise_error(ERR_CLASS_CLOSED, "share class is closed to new subscriptions")

    sub = stamp_new({
        "investor_id": investor["id"],
        "share_class_id": share_class["id"],
        "commitment_amount_cents": commitment,
        "funded_amount_cents": 0,
        "funding_deadline_utc": funding_deadline,
        "late_fees_accrued_cents": 0,
        "effective_series_id": None,
        "status": "DRAFT",
        "_fund_id": fund["id"],
        "_lockup_base_ts": None,
        "_rejection_reason": None,
    })
    db["subscriptions"][sub["id"]] = sub
    return success_object(serialize(sub), 201)


@bp.get("/funds/<fund_id>/subscriptions")
def list_subscriptions(fund_id):
    require_roles(*SUB_LISTERS)
    fund = get_fund(fund_id)
    items = filter_by(db["subscriptions"].values(),
                      _fund_id=fund["id"],
                      investor_id=request.args.get("investor_id"),
                      status=request.args.get("status"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/subscriptions/<sub_id>")
def get_subscription_route(fund_id, sub_id):
    caller = require_roles(*SUB_READERS)
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    check_investor_owns(caller, sub["investor_id"])
    return success_object(serialize(sub))


# ---------------------------------------------------------------------------
# Submit / compliance decisions
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/subscriptions/<sub_id>/submit")
def submit_subscription(fund_id, sub_id):
    caller = require_roles("Investor", "TransferAgent")
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    check_investor_owns(caller, sub["investor_id"])
    get_body()
    if sub["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "subscription is not DRAFT")
    investor = get_investor(sub["investor_id"])
    share_class = get_share_class(sub["share_class_id"])
    if investor["kyc_status"] == "REJECTED":
        raise_error(ERR_KYC_REJECTED, "investor KYC is REJECTED")
    if not share_class["is_open_for_subscription"]:
        raise_error(ERR_CLASS_CLOSED, "share class is closed to new subscriptions")
    if sub["commitment_amount_cents"] < share_class["min_initial_investment_cents"]:
        raise_error(ERR_BELOW_MIN_INVESTMENT,
                    "commitment_amount_cents below min_initial_investment_cents")

    # Side effect: auto-open a KYC case when none is OPEN or IN_REVIEW.
    has_active_case = any(
        c["investor_id"] == investor["id"] and c["status"] in ("OPEN", "IN_REVIEW")
        for c in db["kyc_cases"].values())
    if not has_active_case:
        open_kyc_case(investor, "LOW", False, False, False)

    sub["status"] = "SUBMITTED"
    touch(sub)
    # Auto-transition to KYC_HOLD unless the investor is already APPROVED.
    if investor["kyc_status"] in ("NOT_STARTED", "DOCUMENTS_PENDING", "UNDER_REVIEW"):
        sub["status"] = "KYC_HOLD"
        touch(sub)
    return success_object(serialize(sub))


@bp.post("/funds/<fund_id>/subscriptions/<sub_id>/compliance-approve")
def compliance_approve(fund_id, sub_id):
    require_roles("ComplianceOfficer")
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    get_body()
    if sub["status"] not in ("SUBMITTED", "KYC_HOLD"):
        raise_error(ERR_INVALID_STATE,
                    "subscription is not SUBMITTED or KYC_HOLD")
    sub["status"] = "COMPLIANCE_APPROVED"
    touch(sub)
    return success_object(serialize(sub))


@bp.post("/funds/<fund_id>/subscriptions/<sub_id>/compliance-reject")
def compliance_reject(fund_id, sub_id):
    require_roles("ComplianceOfficer")
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    body = get_body()
    if sub["status"] != "COMPLIANCE_APPROVED":
        raise_error(ERR_INVALID_STATE, "subscription is not COMPLIANCE_APPROVED")
    sub["status"] = "REJECTED"
    sub["_rejection_reason"] = opt_str(body, "rejection_reason")
    touch(sub)
    recompute_unfunded(get_investor(sub["investor_id"]))
    return success_object(serialize(sub))


# ---------------------------------------------------------------------------
# Fundings
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/subscriptions/<sub_id>/fundings")
def record_funding(fund_id, sub_id):
    require_roles("TransferAgent")
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    body = get_body()
    amount = req_int(body, "amount_cents")
    received_at = req_datetime(body, "received_at_utc")
    if sub["status"] not in ("COMPLIANCE_APPROVED", "FUNDING_PARTIAL"):
        raise_error(ERR_INVALID_STATE,
                    "subscription is not open for funding receipts")
    # Priority 9 (deadline, logical clock) before priority 20 (amount).
    if CLOCK.now() > __import__("util").parse_datetime(sub["funding_deadline_utc"]):
        raise_error(ERR_FUNDING_DEADLINE_PASSED, "funding deadline has passed")
    if amount <= 0:
        raise_error(ERR_INVALID_AMOUNT, "funding amount must be positive")

    sub["funded_amount_cents"] = min(
        sub["funded_amount_cents"] + amount, sub["commitment_amount_cents"])
    # Lockup base = the logical-clock time of the funding event that advances
    # the funded total; the FUNDED-transition receipt is the one that counts.
    sub["_lockup_base_ts"] = CLOCK.now_iso()
    if sub["funded_amount_cents"] >= sub["commitment_amount_cents"]:
        sub["status"] = "FUNDED"
    else:
        sub["status"] = "FUNDING_PARTIAL"
    touch(sub)
    recompute_unfunded(get_investor(sub["investor_id"]))
    return success_object(serialize(sub), 201)


# ---------------------------------------------------------------------------
# Accept / cancel
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/subscriptions/<sub_id>/accept")
def accept_subscription(fund_id, sub_id):
    require_roles("FundAdmin")
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    body = get_body()
    if sub["status"] != "FUNDED":
        raise_error(ERR_INVALID_STATE, "subscription is not FUNDED")

    share_class = get_share_class(sub["share_class_id"])

    # Priority 18: nominated effective_series_id must be an OPEN series of the
    # subscription's share class.
    nominated_series_id = opt_str(body, "effective_series_id")
    series = None
    if nominated_series_id is not None:
        candidate = db["series"].get(nominated_series_id)
        if (candidate is None or candidate["share_class_id"] != share_class["id"]
                or candidate["status"] != "OPEN"):
            raise_error(ERR_SERIES_MISMATCH,
                        "effective_series_id is not an OPEN series of this share class")
        series = candidate

    # Priority 19: fund must have an open NAV period.
    if fund["current_nav_period_id"] is None:
        raise_error(ERR_NO_OPEN_NAV_PERIOD, "fund has no open NAV period")
    period = get_nav_period(fund["current_nav_period_id"])

    # Priority 22 (last): OCC against Fund.version.
    expected = opt_int(body, "expected_fund_version")
    if expected is not None and expected != fund["version"]:
        raise_error(ERR_STALE_VERSION, "expected_fund_version does not match fund version")

    if series is None:
        series = current_open_series(share_class)

    funded = sub["funded_amount_cents"]
    locked_until = compute_locked_until(
        sub["_lockup_base_ts"] or CLOCK.now_iso(), share_class["lockup_months"])

    account = stamp_new({
        "investor_id": sub["investor_id"],
        "share_class_id": share_class["id"],
        "subscription_id": sub["id"],
        "current_balance_cents": funded,
        "high_water_mark_cents": funded,
        "accrued_performance_fee_cents": 0,
        "equalization_deposit_cents": 0,
        "locked_until_utc": locked_until,
        "status": "ACTIVE",
        "effective_fee_bps": base_fee_bps(share_class),
        "_fund_id": fund["id"],
    })
    reset_period_accumulators(account, 0)
    account["_period_contributions"] = funded
    db["capital_accounts"][account["id"]] = account

    nav = class_nav_per_share(share_class)
    shares = float(__import__("decimal").Decimal(funded) / nav)
    lot = stamp_new({
        "capital_account_id": account["id"],
        "series_id": series["id"],
        "nav_period_id": period["id"],
        "shares": shares,
        "cost_basis_cents": funded,
        "current_value_cents": funded,
        "equalization_credit_cents": 0,
        "status": "OUTSTANDING",
    })
    db["series_lots"][lot["id"]] = lot

    sub["status"] = "ACCEPTED"
    sub["effective_series_id"] = series["id"]
    touch(sub)

    fund["total_net_assets_cents"] += funded
    touch(fund)
    recompute_unfunded(get_investor(sub["investor_id"]))
    return success_object(serialize(sub))


@bp.post("/funds/<fund_id>/subscriptions/<sub_id>/cancel")
def cancel_subscription(fund_id, sub_id):
    require_roles("FundAdmin")
    fund, sub = _load_sub_under_fund(fund_id, sub_id)
    get_body()
    if sub["status"] != "FUNDING_PARTIAL":
        raise_error(ERR_INVALID_STATE, "only FUNDING_PARTIAL subscriptions can be cancelled")
    deadline = __import__("util").parse_datetime(sub["funding_deadline_utc"])
    now = CLOCK.now()
    if now <= deadline:
        raise_error(ERR_INVALID_STATE, "funding deadline has not passed")

    # Late fee: per-day round-half-up, then summed (pinned rounding order).
    days_late = (now - deadline).days
    per_day = round_half_up_int(sub["funded_amount_cents"] * 5, 10000)
    sub["late_fees_accrued_cents"] += per_day * days_late
    sub["status"] = "CANCELLED"
    touch(sub)
    recompute_unfunded(get_investor(sub["investor_id"]))
    return success_object(serialize(sub))
