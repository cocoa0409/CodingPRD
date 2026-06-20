"""Calculation rules (PRD §3 / SCAFFOLD §1.3).

All money is integer cents, round_half_up. These functions are pure given the
records they read from the store.
"""

from db import store
from services.common import (
    round_half_up_int,
    round_half_up_therms,
    parse_dt,
    clock_now,
)

# --- Constants (SCAFFOLD §1.3) ---
PAYMENT_TERM_DAYS = 21
THERM_DECIMALS = 1

BUDGET_MONTHS = 12

FPL_BASE_CENTS = 1509000
FPL_PER_PERSON_CENTS = 532000
TIER_1_FPL_RATIO = 1.00
TIER_2_FPL_RATIO = 1.50

TIER_1_DISCOUNT_PCT = 0.20
TIER_2_DISCOUNT_PCT = 0.10
TIER_1_MONTHLY_CAP_CENTS = 4000
TIER_2_MONTHLY_CAP_CENTS = 2500

DEPOSIT_RES_CENTS = 15000
DEPOSIT_COM_CENTS = 40000
DELINQUENCY_MULTIPLIER = 1.5
DEPOSIT_WAIVE_ONTIME_COUNT = 12
DEPOSIT_REFUND_ONTIME_COUNT = 12

SHUTOFF_THRESHOLD_CENTS = 7500
MORATORIUM_MONTHS = {11, 12, 1, 2, 3}


# ---------------------------------------------------------------------------
# Winter moratorium (PRD §3.9 / calc winter_moratorium)
# ---------------------------------------------------------------------------
def winter_moratorium_in_effect():
    now = clock_now()
    in_window = now.month in MORATORIUM_MONTHS
    return in_window and bool(store.clock["heating_season_active"])


# ---------------------------------------------------------------------------
# Consumption conversion (PRD §3.4 / calc consumption_conversion)
# ---------------------------------------------------------------------------
def prior_index_for(meter, read_date_dt, exclude_read_id=None):
    """Most recent non-VOID read on the same meter with read_date strictly
    earlier than read_date_dt; else the meter's install_index. Ties broken by
    created_at ASC (the _seq).
    """
    candidates = []
    for r in store.meter_reads.values():
        if r["premise_meter_id"] != meter["id"]:
            continue
        if r["status"] == "VOID":
            continue
        if exclude_read_id is not None and r["id"] == exclude_read_id:
            continue
        rd = parse_dt(r["read_date"])
        if rd < read_date_dt:
            candidates.append((rd, r["_seq"], r))
    if not candidates:
        return meter["install_index"]
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[-1][2]["reading_index"]


def compute_consumption(meter, reading_index, read_date_dt, exclude_read_id=None):
    """Return (ccf_consumed, therms_consumed, raw_delta). Caller checks rollback."""
    prior = prior_index_for(meter, read_date_dt, exclude_read_id=exclude_read_id)
    raw_delta = reading_index - prior
    ccf_consumed = raw_delta
    if meter["uom"] == "CCF":
        rate_schedule = _account_rate_schedule(meter["account_id"])
        btu = rate_schedule["btu_factor"]
        therms_unrounded = ccf_consumed * btu
    else:
        therms_unrounded = ccf_consumed
    therms_consumed = round_half_up_therms(therms_unrounded)
    return ccf_consumed, therms_consumed, raw_delta


def _account_rate_schedule(account_id):
    account = store.accounts[account_id]
    return store.rate_schedules[account["rate_schedule_id"]]


# ---------------------------------------------------------------------------
# Bill charges (PRD §3.5 / calc bill_charges) — evaluation order is PINNED
# ---------------------------------------------------------------------------
def compute_bill_charges(account, to_read, rate_schedule, pga, low_income_tier):
    """Return a dict of computed charge fields for a single-cycle bill."""
    therms_billed = to_read["therms_consumed"]

    eff_pga = max(0, pga["commodity_rate_cents_per_therm"]
                  - pga["supplier_refund_cents_per_therm"])
    commodity_charge_cents = round_half_up_int(therms_billed * eff_pga)

    distribution_charge_cents = round_half_up_int(
        therms_billed * rate_schedule["distribution_rate_cents_per_therm"])
    fixed_charge_cents = rate_schedule["fixed_customer_charge_cents"]

    gross = commodity_charge_cents + distribution_charge_cents + fixed_charge_cents
    gross = max(gross, rate_schedule["minimum_bill_cents"])

    low_income_credit_cents = compute_low_income_credit(
        commodity_charge_cents, distribution_charge_cents, low_income_tier)

    amount_due_cents = max(0, gross - low_income_credit_cents)

    return {
        "therms_billed": therms_billed,
        "commodity_charge_cents": commodity_charge_cents,
        "distribution_charge_cents": distribution_charge_cents,
        "fixed_charge_cents": fixed_charge_cents,
        "low_income_credit_cents": low_income_credit_cents,
        "amount_due_cents": amount_due_cents,
    }


# ---------------------------------------------------------------------------
# Low-income credit (PRD §3.8 / calc low_income_credit)
# ---------------------------------------------------------------------------
def compute_low_income_credit(commodity_cents, distribution_cents, tier):
    if tier == "TIER_1":
        pct = TIER_1_DISCOUNT_PCT
        cap = TIER_1_MONTHLY_CAP_CENTS
    elif tier == "TIER_2":
        pct = TIER_2_DISCOUNT_PCT
        cap = TIER_2_MONTHLY_CAP_CENTS
    else:
        return 0
    creditable = commodity_cents + distribution_cents
    return min(round_half_up_int(creditable * pct), cap)


# ---------------------------------------------------------------------------
# Low-income eligibility tier (PRD §3.8 / calc low_income_eligibility)
# ---------------------------------------------------------------------------
def compute_low_income_tier(household_size, annual_income_cents):
    fpl = FPL_BASE_CENTS + (household_size - 1) * FPL_PER_PERSON_CENTS
    ratio = annual_income_cents / fpl
    if ratio <= TIER_1_FPL_RATIO:
        return "TIER_1"
    elif ratio <= TIER_2_FPL_RATIO:
        return "TIER_2"
    return "NONE"


# ---------------------------------------------------------------------------
# Budget installment (PRD §3.7 / calc budget_installment)
# ---------------------------------------------------------------------------
def compute_monthly_installment(projected_annual_cents):
    return round_half_up_int(projected_annual_cents / BUDGET_MONTHS)


# ---------------------------------------------------------------------------
# Deposit requirement (PRD §3.11 / calc deposit_requirement)
# ---------------------------------------------------------------------------
def compute_deposit_requirement(account, reason):
    if account["low_income_status"] == "ENROLLED":
        return 0
    if account["consecutive_ontime_payments"] >= DEPOSIT_WAIVE_ONTIME_COUNT:
        return 0
    base = DEPOSIT_RES_CENTS if account["customer_class"] == "RESIDENTIAL" else DEPOSIT_COM_CENTS
    if reason == "DELINQUENCY":
        base = round_half_up_int(base * DELINQUENCY_MULTIPLIER)
    return base


# ---------------------------------------------------------------------------
# Ticket severity (PRD §3.13 / calc ticket_severity)
# ---------------------------------------------------------------------------
def compute_ticket_severity(kind, reported_indoors):
    if kind == "LEAK" and reported_indoors:
        return "GRADE_1", 60
    elif kind == "CARBON_MONOXIDE":
        return "GRADE_1", 60
    elif kind == "LEAK" and not reported_indoors:
        return "GRADE_2", 240
    elif kind == "ODOR" and reported_indoors:
        return "GRADE_2", 240
    else:  # ODOR outdoors
        return "GRADE_3", 1440


# ---------------------------------------------------------------------------
# Payment timeliness (PRD §3.12 / calc payment_timeliness)
# ---------------------------------------------------------------------------
def is_on_time(posted_date_dt, bill):
    due = parse_dt(bill["due_date"])
    return posted_date_dt <= due


# ---------------------------------------------------------------------------
# Account computed balances (PRD §3.9, §3.11) — recomputed on read
# ---------------------------------------------------------------------------
def account_balance_cents(account_id):
    """Sum of ISSUED-onward bill amount_due_cents minus POSTED payments.

    PRD §3.9: balance_cents = sum of amount_due_cents across issued bills minus
    sum of amount_cents across posted payments. A CORRECTED bill is superseded
    by its rebill, so only non-CORRECTED, non-VOID, non-DRAFT bills count.
    """
    issued = 0
    for b in store.bills.values():
        if b["account_id"] != account_id:
            continue
        if b["status"] in ("ISSUED", "PAID"):
            issued += b["amount_due_cents"]
    paid = 0
    for p in store.payments.values():
        if p["account_id"] != account_id:
            continue
        if p["status"] == "POSTED":
            paid += p["amount_cents"]
    return issued - paid


def account_past_due_cents(account_id):
    """Sum of amount_due_cents over ISSUED bills whose due_date is strictly
    before the clock date and which are not fully paid (PRD §3.9).
    """
    now = clock_now()
    total = 0
    for b in store.bills.values():
        if b["account_id"] != account_id:
            continue
        if b["status"] != "ISSUED":
            continue
        if not b.get("due_date"):
            continue
        due = parse_dt(b["due_date"])
        if due < now and b["paid_cents"] < b["amount_due_cents"]:
            total += b["amount_due_cents"]
    return total


def account_deposit_held_cents(account_id):
    """Sum of HELD deposit amounts net of REFUNDED/APPLIED (PRD §3.11)."""
    total = 0
    for d in store.deposits.values():
        if d["account_id"] != account_id:
            continue
        if d["status"] == "HELD":
            total += d["amount_cents"]
    return total


def account_shutoff_eligible(account_id):
    past_due = account_past_due_cents(account_id)
    return (past_due >= SHUTOFF_THRESHOLD_CENTS) and (not winter_moratorium_in_effect())
