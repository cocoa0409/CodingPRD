"""FundAccount, FundLedgerEntry, FeeAssessment endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import new_id, parse_iso_date, stamp_new, store, touch
from envelope import ok_list, ok_obj
from errors import (
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_CLOSE_PERIOD_INVALID,
    ERR_FUND_ACCOUNT_NOT_FOUND,
    ERR_FUND_NOT_ACTIVE,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_STALE_FUND_VERSION,
    ERR_VALIDATION,
    raise_err,
)
from security import (
    READ_ROLES,
    auth,
    body,
    req_int,
    req_str,
    require_role,
)
from services import (
    ANNUAL_PLATFORM_FEE_CENTS,
    available_cents,
    forward_available_cents,
    post_ledger,
    rhu,
)

bp = Blueprint("funds", __name__)

LEDGER_ENTRY_TYPES = (
    "DONATION_CREDIT", "FEE_DEBIT", "DONATION_REFUND_DEBIT", "FEE_REVERSAL_CREDIT",
    "COMMITMENT_HOLD", "COMMITMENT_RELEASE", "DISBURSEMENT_DEBIT", "ADJUSTMENT",
    "RESERVE_HOLD", "EXIT_TRANSFER_DEBIT",
)


def get_fund(fund_id):
    fund = store.funds.get(fund_id)
    if fund is None:
        raise_err(ERR_FUND_ACCOUNT_NOT_FOUND, "fund account not found")
    return fund


def fund_view(fund):
    from db import public
    view = public(fund)
    view["available_cents"] = available_cents(fund)
    view["forward_available_cents"] = forward_available_cents(fund)
    return view


@bp.get("/fsa/fund-accounts/<fund_id>")
def get_fund_route(fund_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    from envelope import ok
    return ok(fund_view(get_fund(fund_id)))


@bp.get("/fsa/projects/<project_id>/fund-accounts")
def project_fund_accounts(project_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    if project_id not in store.projects:
        raise_err(ERR_PROJECT_NOT_FOUND, "project not found")
    items = [f for f in store.funds.values() if f["project_id"] == project_id]
    # fund view carries derived balances; ok_list serializes via public() so
    # attach derived fields on a copy for the listing
    derived = []
    for f in items:
        v = dict(f)
        v["available_cents"] = available_cents(f)
        v["forward_available_cents"] = forward_available_cents(f)
        derived.append(v)
    return ok_list(derived)


@bp.post("/fsa/fund-accounts/<fund_id>/adjustments")
def post_adjustment(fund_id):
    data = body()
    expected_version = req_int(data, "expected_fund_account_version")
    amount = req_int(data, "amount_cents")
    memo = req_str(data, "memo")
    uid, role = auth()
    require_role(role, {"FinanceOfficer"})
    fund = get_fund(fund_id)
    if fund["status"] == "CLOSED":
        raise_err(ERR_FUND_NOT_ACTIVE, "a CLOSED fund accepts no further movement")
    if expected_version != fund["version"]:
        raise_err(ERR_STALE_FUND_VERSION, "expected_fund_account_version does not match current version")
    fund["total_adjustments_cents"] += amount
    post_ledger(fund["id"], "ADJUSTMENT", amount, memo)
    touch(fund)
    from envelope import ok
    return ok(fund_view(fund))


@bp.post("/fsa/fund-accounts/<fund_id>/close-period")
def close_period(fund_id):
    data = body()
    period_start = req_str(data, "period_start")
    period_end = req_str(data, "period_end")
    start = parse_iso_date(period_start)
    end = parse_iso_date(period_end)
    if start is None:
        raise_err(ERR_VALIDATION, "period_start must be an ISO date (YYYY-MM-DD)")
    if end is None:
        raise_err(ERR_VALIDATION, "period_end must be an ISO date (YYYY-MM-DD)")
    uid, role = auth()
    require_role(role, {"FinanceOfficer"})
    fund = get_fund(fund_id)
    if fund["status"] == "CLOSED":
        raise_err(ERR_FUND_NOT_ACTIVE, "a CLOSED fund accepts no further movement")
    if end < start:
        raise_err(ERR_CLOSE_PERIOD_INVALID, "period_end is earlier than period_start")
    from db import agreement_of_project
    agreement = agreement_of_project(fund["project_id"])
    model = agreement["model"] if agreement else None
    # period donations: received_at date in [period_start, period_end] inclusive,
    # ordered by received_at then created_at (ids never used)
    period_donations = []
    for d in store.donations.values():
        if d["fund_account_id"] != fund["id"] or not d["received_at"]:
            continue
        d_date = parse_iso_date(d["received_at"][:10])
        if start <= d_date <= end:
            period_donations.append(d)
    period_donations.sort(key=lambda d: (d["received_at"], d["created_at"], d.get("_seq", 0)))
    provisional = sum(d["fee_cents"] for d in period_donations)
    refund_reversals = 0
    annual_platform_fee = 0
    if model == "PRE_APPROVED_GRANT":
        # grant fees are not reversed; annual platform fee on the first FINAL
        # close whose period_end year had at least one received donation
        year = end.year
        had_receipt_in_year = any(
            d["received_at"] and parse_iso_date(d["received_at"][:10]).year == year
            for d in store.donations.values()
            if d["fund_account_id"] == fund["id"]
        )
        prior_final_in_year = any(
            a["fund_account_id"] == fund["id"] and parse_iso_date(a["period_end"]).year == year
            for a in store.assessments.values()
        )
        if had_receipt_in_year and not prior_final_in_year:
            annual_platform_fee = ANNUAL_PLATFORM_FEE_CENTS
    else:
        from decimal import Decimal
        for d in period_donations:
            if d["refunded_cents"] > 0:
                kept = rhu(
                    Decimal(d["fee_cents"])
                    * Decimal(d["amount_cents"] - d["refunded_cents"])
                    / Decimal(d["amount_cents"])
                )
                refund_reversals += d["fee_cents"] - kept
    final_fees = provisional - refund_reversals + annual_platform_fee
    delta = final_fees - provisional
    if delta < 0:
        post_ledger(fund["id"], "FEE_REVERSAL_CREDIT", -delta,
                    "Fee reversal at period close %s..%s" % (period_start, period_end))
    elif delta > 0:
        post_ledger(fund["id"], "FEE_DEBIT", -delta,
                    "Fee assessment at period close %s..%s" % (period_start, period_end))
    fund["total_fees_reversed_cents"] += refund_reversals
    fund["total_fees_charged_cents"] += annual_platform_fee
    touch(fund)
    assessment = stamp_new({
        "id": new_id(),
        "fund_account_id": fund["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "FINAL",
        "provisional_fees_cents": provisional,
        "refund_reversals_cents": refund_reversals,
        "annual_platform_fee_cents": annual_platform_fee,
        "final_fees_cents": final_fees,
        "delta_cents": delta,
    })
    store.assessments[assessment["id"]] = assessment
    return ok_obj(assessment)


# ---------------------------------------------------------------------------
# Ledger reads
# ---------------------------------------------------------------------------


@bp.get("/fsa/fund-accounts/<fund_id>/ledger-entries")
def fund_ledger_entries(fund_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    get_fund(fund_id)
    items = [e for e in store.ledger_entries.values() if e["fund_account_id"] == fund_id]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    return ok_list(items)


@bp.get("/fsa/fund-ledger-entries")
def list_ledger_entries():
    uid, role = auth()
    require_role(role, READ_ROLES)
    items = list(store.ledger_entries.values())
    for param in ("fund_account_id", "donation_id", "disbursement_id", "entry_type"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[param] == v]
    return ok_list(items)


@bp.get("/fsa/fund-ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    entry = store.ledger_entries.get(entry_id)
    if entry is None:
        raise_err(ERR_LEDGER_ENTRY_NOT_FOUND, "ledger entry not found")
    return ok_obj(entry)


# ---------------------------------------------------------------------------
# Fee assessment reads
# ---------------------------------------------------------------------------


@bp.get("/fsa/fund-accounts/<fund_id>/fee-assessments")
def fund_assessments(fund_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    get_fund(fund_id)
    items = [a for a in store.assessments.values() if a["fund_account_id"] == fund_id]
    return ok_list(items)


@bp.get("/fsa/fee-assessments/<assessment_id>")
def get_assessment(assessment_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    assessment = store.assessments.get(assessment_id)
    if assessment is None:
        raise_err(ERR_ASSESSMENT_NOT_FOUND, "fee assessment not found")
    return ok_obj(assessment)
