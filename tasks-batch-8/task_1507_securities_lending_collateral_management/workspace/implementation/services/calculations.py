"""Calculation rules — all 12 from SCAFFOLD §1.3."""

from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def round_half_up_cents(value_decimal):
    """Round a Decimal to integer cents, half-up."""
    return int(value_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(val):
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# 1. required_collateral_value
# ---------------------------------------------------------------------------

def compute_required_collateral_cents(loan, security):
    margin_bps = 10200 if loan["collateral_type"] == "CASH" else 10500
    raw = _dec(loan["outstanding_quantity"]) * _dec(security["price_cents"]) * _dec(margin_bps) / _dec(10000)
    return round_half_up_cents(raw)


# ---------------------------------------------------------------------------
# 2. posted_collateral_value
# ---------------------------------------------------------------------------

HAIRCUT_BPS = {"GOV_BOND": 200, "CORP_BOND": 600, "EQUITY": 1000}


def compute_pledge_marked_value(pledge):
    """Per-pledge rounding: round each pledge FIRST, then sum."""
    if pledge["pledge_type"] == "CASH":
        return pledge["amount_cents"]
    # SECURITY
    sec = db.securities[pledge["pledge_security_id"]]
    haircut = sec["haircut_bps"]
    raw = _dec(pledge["quantity"]) * _dec(sec["price_cents"]) * _dec(10000 - haircut) / _dec(10000)
    return round_half_up_cents(raw)


def compute_posted_collateral_cents(loan_id):
    total = 0
    for p in db.pledges.values():
        if p["loan_id"] == loan_id and p["status"] == "ACTIVE":
            p["marked_value_cents"] = compute_pledge_marked_value(p)
            total += p["marked_value_cents"]
    return total


# ---------------------------------------------------------------------------
# 3. margin_deficit_and_call_issuance
# ---------------------------------------------------------------------------

def get_open_margin_calls(loan_id):
    """Return list of (call_id, call_dict) for OPEN or ESCALATED calls on the loan."""
    result = []
    for cid, mc in db.margin_calls.items():
        if mc["loan_id"] == loan_id and mc["status"] in ("OPEN", "ESCALATED"):
            result.append((cid, mc))
    return result


def evaluate_cure(loan):
    """After any collateral/price change: if deficit <= 0, cure all open calls."""
    if loan["status"] not in ("BOOKED", "RECALLED"):
        return
    sec = db.securities[loan["security_id"]]
    required = compute_required_collateral_cents(loan, sec)
    posted = compute_posted_collateral_cents(loan["id"])
    loan["required_collateral_cents"] = required
    loan["posted_collateral_cents"] = posted
    deficit = required - posted
    if deficit <= 0:
        for _, mc in get_open_margin_calls(loan["id"]):
            mc["status"] = "CURED"
            mc["updated_at"] = db.now_iso()
            mc["version"] += 1
        _recompute_margin_status(loan)


def _recompute_margin_status(loan):
    has_open = any(
        mc["status"] in ("OPEN", "ESCALATED")
        for mc in db.margin_calls.values()
        if mc["loan_id"] == loan["id"]
    )
    loan["margin_status"] = "CALL_OPEN" if has_open else "CURRENT"


# ---------------------------------------------------------------------------
# 4. loan_fee_accrual
# ---------------------------------------------------------------------------

def compute_daily_fee(outstanding_qty, price_cents, rate_bps):
    """Provisional daily fee, round_half_up per day."""
    raw = _dec(outstanding_qty) * _dec(price_cents) * _dec(rate_bps) / _dec(10000) / _dec(360)
    return round_half_up_cents(raw)


def compute_period_fee_exact(day_entries):
    """Sum of unrounded daily fees. Each entry: (outstanding_qty, price_cents, rate_bps)."""
    total = Decimal("0")
    for qty, price, rate in day_entries:
        total += _dec(qty) * _dec(price) * _dec(rate) / _dec(10000) / _dec(360)
    return total


# ---------------------------------------------------------------------------
# 5. rebate_accrual
# ---------------------------------------------------------------------------

def compute_daily_rebate(active_cash_cents, rate_bps):
    raw = _dec(active_cash_cents) * _dec(rate_bps) / _dec(10000) / _dec(360)
    return round_half_up_cents(raw)


# ---------------------------------------------------------------------------
# 6. reinvestment_income
# ---------------------------------------------------------------------------

def compute_daily_reinvest_income(principal_cents, stated_yield_bps):
    raw = _dec(principal_cents) * _dec(stated_yield_bps) / _dec(10000) / _dec(360)
    return round_half_up_cents(raw)


# ---------------------------------------------------------------------------
# 7. borrower_utilization_bps
# ---------------------------------------------------------------------------

def compute_utilization_cents(borrower_id):
    total = 0
    for loan in db.loans.values():
        if loan["borrower_id"] == borrower_id and loan["status"] in ("BOOKED", "RECALLED"):
            sec = db.securities[loan["security_id"]]
            total += loan["outstanding_quantity"] * sec["price_cents"]
    return total


def compute_effective_limit_cents(borrower):
    """Check for APPROVED non-expired override covering current date."""
    current = db.current_date_str()
    for ov in db.limit_overrides.values():
        if (ov["borrower_id"] == borrower["id"]
                and ov["status"] == "APPROVED"
                and ov["effective_from"] <= current < ov["expires_at"]):
            return ov["new_limit_cents"]
    return borrower["credit_limit_cents"]


def compute_utilization_bps(borrower_id, effective_limit_cents, additional_value=0):
    util = compute_utilization_cents(borrower_id) + additional_value
    if effective_limit_cents <= 0:
        return 999999
    return (util * 10000) // effective_limit_cents


# ---------------------------------------------------------------------------
# 8. forward_capacity_check
# ---------------------------------------------------------------------------

def check_forward_capacity(position, new_quantity, term_days, exclude_loan_id=None):
    """Returns True if capacity OK, False if exceeded.
    W = [current_date, current_date + term_days), or all days from current_date if term_days is None.
    """
    from datetime import timedelta
    current = db.clock.now().date()
    if term_days is None:
        # Open term: check a far horizon (e.g., 3650 days)
        end = current + timedelta(days=3650)
    else:
        end = current + timedelta(days=term_days)

    # Build daily occupancy from existing loans on this position
    # occupied(d) = quantity_on_loan + sum of PROPOSED/COUNTERED loans covering d
    # For the check at booking (exclude_loan_id set), exclude the converting loan.
    on_loan = position["quantity_on_loan"]

    # Collect all reservation windows
    reservations = []
    for loan in db.loans.values():
        if loan["position_id"] != position["id"]:
            continue
        if exclude_loan_id and loan["id"] == exclude_loan_id:
            continue
        if loan["status"] not in ("PROPOSED", "COUNTERED"):
            continue
        loan_start = _loan_window_start(loan)
        loan_end = _loan_window_end(loan)
        reservations.append((loan_start, loan_end, loan["quantity"]))

    # Walk each day in window
    from datetime import date as date_type
    d = current
    while d < end:
        occupied = on_loan
        for r_start, r_end, r_qty in reservations:
            if r_start <= d < r_end:
                occupied += r_qty
        if occupied + new_quantity > position["quantity_total"]:
            return False
        d += timedelta(days=1)
    return True


def _loan_window_start(loan):
    """The window starts from the loan's created_at date (or current date if not yet created)."""
    from datetime import datetime
    created = loan.get("_window_start_date")
    if created:
        return created
    # Parse created_at to date
    ts = loan["created_at"]
    return datetime.strptime(ts[:10], "%Y-%m-%d").date()


def _loan_window_end(loan):
    from datetime import timedelta
    start = _loan_window_start(loan)
    if loan.get("term_days") is not None:
        return start + timedelta(days=loan["term_days"])
    # Open term
    return start + timedelta(days=3650)


# ---------------------------------------------------------------------------
# 9. fail_fee_accrual
# ---------------------------------------------------------------------------

FAIL_FEE_BPS = 100


def compute_fail_fee_for_tranche(shares, fail_price_cents, fee_days):
    """fee = fee_days * round_half_up(shares * fail_price_cents * 100 / 10000)"""
    per_day = round_half_up_cents(_dec(shares) * _dec(fail_price_cents) * _dec(FAIL_FEE_BPS) / _dec(10000))
    return fee_days * per_day


# ---------------------------------------------------------------------------
# 10. buy_in_charge
# ---------------------------------------------------------------------------

def compute_buy_in_charge(undelivered, buy_in_price_cents):
    return undelivered * buy_in_price_cents


# ---------------------------------------------------------------------------
# 11. revenue_split_waterfall
# ---------------------------------------------------------------------------

def compute_revenue_split(owner, period):
    """Returns (owner_share, agent_share, net_pool)."""
    gross = 0
    rebates = 0
    for entry in db.ledger_entries.values():
        if entry.get("period") != period:
            continue
        # Only entries for loans owned by this owner
        if entry["entry_type"] in ("FEE_ACCRUAL_FINAL", "REINVEST_INCOME_FINAL"):
            if entry.get("loan_id"):
                loan = db.loans.get(entry["loan_id"])
                if loan and loan["owner_id"] == owner["id"]:
                    gross += entry["amount_cents"]
        elif entry["entry_type"] == "REBATE_ACCRUAL":
            if entry.get("loan_id"):
                loan = db.loans.get(entry["loan_id"])
                if loan and loan["owner_id"] == owner["id"]:
                    rebates += (-entry["amount_cents"])  # stored negative, negate

    net_pool = gross - rebates
    owner_share = round_half_up_cents(_dec(net_pool) * _dec(owner["revenue_share_bps"]) / _dec(10000))
    agent_share = net_pool - owner_share
    return owner_share, agent_share, net_pool


# ---------------------------------------------------------------------------
# 12. indemnity_shortfall
# ---------------------------------------------------------------------------

def compute_indemnity_shortfall(loan, seized_pledge_values):
    """owed = market_value at default + outstanding unpaid finalized fees
       seized = sum of just-seized pledge marked values
       shortfall = max(0, owed - seized)"""
    owed = loan["market_value_cents"]
    # Add outstanding unpaid finalized fees (FEE_ACCRUAL_FINAL entries for this loan)
    for entry in db.ledger_entries.values():
        if entry.get("loan_id") == loan["id"] and entry["entry_type"] == "FEE_ACCRUAL_FINAL":
            owed += entry["amount_cents"]
    seized = sum(seized_pledge_values)
    return max(0, owed - seized)


# ---------------------------------------------------------------------------
# Common computed field updates
# ---------------------------------------------------------------------------

def recompute_loan_derived(loan):
    """Recompute market_value_cents, required_collateral_cents, posted_collateral_cents,
    cash_uninvested_cents, margin_status."""
    sec = db.securities[loan["security_id"]]
    loan["market_value_cents"] = loan["outstanding_quantity"] * sec["price_cents"]
    loan["required_collateral_cents"] = compute_required_collateral_cents(loan, sec)
    loan["posted_collateral_cents"] = compute_posted_collateral_cents(loan["id"])

    # cash_uninvested = sum(ACTIVE cash pledges) - sum(INVESTED tranche principals)
    cash_total = sum(
        p["amount_cents"]
        for p in db.pledges.values()
        if p["loan_id"] == loan["id"] and p["status"] == "ACTIVE" and p["pledge_type"] == "CASH"
    )
    invested_total = sum(
        t["principal_cents"]
        for t in db.reinvestments.values()
        if t["loan_id"] == loan["id"] and t["status"] == "INVESTED"
    )
    loan["cash_uninvested_cents"] = cash_total - invested_total
    _recompute_margin_status(loan)


def recompute_borrower_derived(borrower):
    borrower["effective_limit_cents"] = compute_effective_limit_cents(borrower)
    borrower["utilization_cents"] = compute_utilization_cents(borrower["id"])
    el = borrower["effective_limit_cents"]
    if el > 0:
        borrower["utilization_bps"] = (borrower["utilization_cents"] * 10000) // el
    else:
        borrower["utilization_bps"] = 0


def recompute_position_derived(position):
    reserved = 0
    on_loan = 0
    for loan in db.loans.values():
        if loan["position_id"] != position["id"]:
            continue
        if loan["status"] in ("PROPOSED", "COUNTERED"):
            reserved += loan["quantity"]
        elif loan["status"] in ("BOOKED", "RECALLED"):
            on_loan += loan["outstanding_quantity"]
    position["quantity_reserved"] = reserved
    position["quantity_on_loan"] = on_loan
    position["quantity_available"] = position["quantity_total"] - reserved - on_loan
