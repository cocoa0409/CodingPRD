"""Calculation rules (SCAFFOLD 1.3 / PRD 3). All money is integer cents."""

import math
from datetime import timedelta
from decimal import Decimal

from common import round_half_up_cents
from db import store, parse_iso, iso_millis
from services import ledger
from services.serialize import total_current_support_cents

# Constants (SCAFFOLD 1.3)
CAP_SECOND_FAMILY_UNDER_12 = Decimal("0.50")
CAP_SECOND_FAMILY_12_PLUS = Decimal("0.55")
CAP_NO_SECOND_FAMILY_UNDER_12 = Decimal("0.60")
CAP_NO_SECOND_FAMILY_12_PLUS = Decimal("0.65")
WEEKS_THRESHOLD = 12
DAYS_PER_YEAR = 365
BPS_DENOMINATOR = 10000
ENFORCEMENT_CERT_THRESHOLD_CENTS = 50000


# --- arrears_distribution_rule_derivation ------------------------------------
def derive_distribution_rule(assistance_status):
    if assistance_status == "NEVER_ASSISTED":
        return "FAMILY_FIRST"
    return "STATE_FIRST"


# --- ccpa_withholding_cap ----------------------------------------------------
def _arrears_weeks_overdue(ncp):
    """floor( sum(arrears_principal over ACTIVE/MODIFIED orders) /
              weekly-equivalent of total_current_support_cents ).

    The weekly equivalent of a MONTHLY obligation is monthly * 12 / 52.
    If there is no current-support basis (weekly equivalent == 0), weeks = 0.
    """
    ncp_id = ncp["id"]
    arrears_sum = 0
    for o in store.support_orders.values():
        if o["noncustodial_party_id"] != ncp_id:
            continue
        if o["obligation_status"] in ("ACTIVE", "MODIFIED"):
            arrears_sum += ledger.arrears_principal_cents(o["id"])
    monthly_cs = total_current_support_cents(ncp_id)
    if monthly_cs <= 0:
        return 0
    weekly_equiv = Decimal(monthly_cs) * Decimal(12) / Decimal(52)
    if weekly_equiv <= 0:
        return 0
    weeks = Decimal(arrears_sum) / weekly_equiv
    return int(math.floor(weeks))


def compute_ccpa(ncp, disposable_earnings_cents, gross_remitted_cents):
    second_family = bool(ncp["supports_second_family"])
    weeks = _arrears_weeks_overdue(ncp)
    if second_family and weeks < WEEKS_THRESHOLD:
        cap_pct = CAP_SECOND_FAMILY_UNDER_12
    elif second_family and weeks >= WEEKS_THRESHOLD:
        cap_pct = CAP_SECOND_FAMILY_12_PLUS
    elif (not second_family) and weeks < WEEKS_THRESHOLD:
        cap_pct = CAP_NO_SECOND_FAMILY_UNDER_12
    else:
        cap_pct = CAP_NO_SECOND_FAMILY_12_PLUS
    ccpa_cap_cents = round_half_up_cents(Decimal(disposable_earnings_cents) * cap_pct)
    distributable_cents = min(gross_remitted_cents, ccpa_cap_cents)
    return ccpa_cap_cents, distributable_cents


# --- within_order_waterfall --------------------------------------------------
def within_order_waterfall(order_id, amount):
    """Apply `amount` to one order: CURRENT_SUPPORT -> INTEREST -> PRINCIPAL.

    Returns (applied_current, applied_interest, applied_principal, remainder).
    Uses live ledger-derived balances at call time.
    """
    cs_due = ledger.current_support_due_cents(order_id)
    int_bal = ledger.interest_balance_cents(order_id)
    prin_bal = ledger.arrears_principal_cents(order_id)

    applied_current = min(amount, cs_due)
    rem = amount - applied_current
    applied_interest = min(rem, int_bal)
    rem = rem - applied_interest
    applied_principal = min(rem, prin_bal)
    rem = rem - applied_principal
    return applied_current, applied_interest, applied_principal, rem


# --- arrears_interest_accrual ------------------------------------------------
def accrue_interest(order):
    """Compute and post interest.

    Returns True if at least one whole day elapsed (a mutation occurred: a row
    may have posted and last_interest_accrual_at advanced); False if fewer than
    a full day elapsed, in which case nothing changes (PRD 3.6 zero_days).
    """
    last = parse_iso(order["last_interest_accrual_at"])
    if last is None:
        return False
    now = store.clock.now()
    elapsed = (now - last).total_seconds()
    days = int(math.floor(elapsed / 86400.0))
    if days <= 0:
        return False
    principal = ledger.arrears_principal_cents(order["id"])
    rate = Decimal(order["interest_rate_bps"]) / Decimal(BPS_DENOMINATOR)
    raw = Decimal(principal) * rate * Decimal(days) / Decimal(DAYS_PER_YEAR)
    accrued = round_half_up_cents(raw)
    if accrued > 0:
        ledger.post_entry(order["id"], "INTEREST", "INTEREST", accrued, order["id"])
    # Advance last_interest_accrual_at by exactly `days` days (not to the clock),
    # preserving the fractional-day remainder for the next accrual (PRD 3.6).
    order["last_interest_accrual_at"] = iso_millis(last + timedelta(days=days))
    return True


# --- distribution_split ------------------------------------------------------
def distribution_split(order, alloc):
    """Split an allocation slice between family and state (dual-variant)."""
    arrears_collected = alloc["interest_applied_cents"] + alloc["principal_applied_cents"]
    current_collected = alloc["current_support_applied_cents"]
    if order["arrears_distribution_rule"] == "FAMILY_FIRST":
        state_retained = 0
        family_amount = current_collected + arrears_collected
    else:  # STATE_FIRST
        state_retained = min(arrears_collected, order["assigned_arrears_cents"])
        family_amount = current_collected + (arrears_collected - state_retained)
    return family_amount, state_retained


# --- enforcement_certification_threshold -------------------------------------
def certifiable_arrears(order_id):
    return ledger.arrears_principal_cents(order_id) + ledger.interest_balance_cents(order_id)
