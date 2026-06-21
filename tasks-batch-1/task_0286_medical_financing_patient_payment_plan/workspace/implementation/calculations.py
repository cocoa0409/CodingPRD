"""The five calculation rules (SCAFFOLD §1.3 / PRD §3.2, §3.5, §3.7, §3.8, §3.4).

Money is integer cents throughout. round_half_up for rate*cents collapses;
floor() for the credit-decision income band and haircut.
"""
import db
from money import round_half_up, floor_mul
from timeutil import whole_days

# --- credit_decision constants ---
INCOME_MULTIPLIER = 0.20
ABSOLUTE_CAP_CENTS = 2500000
MIN_VIABLE_LINE_CENTS = 50000
DEFAULT_HAIRCUT_PER_PRIOR = 0.25

# --- deferred_interest constants ---
DAYS_PER_YEAR = 360

# --- settlement_fee constants ---
TIER1_THRESHOLD_CENTS = 5000000
TIER2_THRESHOLD_CENTS = 1000000
TIER1_DELTA = 0.02
TIER2_DELTA = 0.01
MIN_RATE = 0.02


# =====================================================================
# credit_decision
# =====================================================================
def credit_provisional(stated_income_cents, requested_limit_cents):
    income_band = floor_mul(stated_income_cents, INCOME_MULTIPLIER)
    provisional = min(requested_limit_cents, income_band, ABSOLUTE_CAP_CENTS)
    if provisional < MIN_VIABLE_LINE_CENTS:
        provisional = 0
    return provisional


def credit_final(stated_income_cents, requested_limit_cents, applicant_full_name):
    base = min(requested_limit_cents,
               floor_mul(stated_income_cents, INCOME_MULTIPLIER),
               ABSOLUTE_CAP_CENTS)
    prior_default_count = 0
    for acc in db.patient_accounts.values():
        if acc["account_holder_name"] == applicant_full_name and acc["status"] == "DEFAULTED":
            prior_default_count += 1
    capped = min(prior_default_count, 3)
    haircut = floor_mul(base, DEFAULT_HAIRCUT_PER_PRIOR * capped)
    approved = max(0, base - haircut)
    if approved < MIN_VIABLE_LINE_CENTS:
        approved = 0
    return approved


# =====================================================================
# settlement_fee
# =====================================================================
def settlement_fee(provider, gross_cents):
    prospective_volume = provider["monthly_settled_volume_cents"] + gross_cents
    if prospective_volume >= TIER1_THRESHOLD_CENTS:
        tier_delta = TIER1_DELTA
    elif prospective_volume >= TIER2_THRESHOLD_CENTS:
        tier_delta = TIER2_DELTA
    else:
        tier_delta = 0.0
    discount_rate_applied = max(MIN_RATE, provider["base_merchant_discount_rate"] - tier_delta)
    discount_fee_cents = round_half_up(gross_cents * discount_rate_applied)
    net_cents = gross_cents - discount_fee_cents
    return discount_rate_applied, discount_fee_cents, net_cents


# =====================================================================
# minimum_payment
# =====================================================================
def minimum_payment(account, closing_balance_cents):
    raw_minimum = 0
    for purchase in db.financed_purchases.values():
        if purchase["patient_account_id"] != account["id"]:
            continue
        if purchase["settlement_status"] in ("REFUNDED", "VOID"):
            continue
        open_principal = purchase["principal_cents"] - purchase["principal_paid_cents"]
        if open_principal <= 0:
            continue
        plan = _plan_for_purchase(purchase)
        factor = plan["min_payment_factor"]
        per_purchase_min = round_half_up(open_principal * factor)
        raw_minimum += per_purchase_min
    return min(raw_minimum, closing_balance_cents)


def _plan_for_purchase(purchase):
    promo = db.provider_promotions[purchase["provider_promotion_id"]]
    return db.promotional_plans[promo["promotional_plan_id"]]


# =====================================================================
# deferred_interest (chronological actual — the only posted variant)
# =====================================================================
def deferred_interest(purchase):
    plan = _plan_for_purchase(purchase)
    promo_apr = plan["promo_apr"]
    daily_rate = promo_apr / DAYS_PER_YEAR
    promo_start = purchase["promo_start"]
    promo_end = purchase["promo_end"]

    # Build in-window allocation events for this purchase: posted_at in
    # [promo_start, promo_end), from POSTED payments only. Each event carries the
    # principal_applied to THIS purchase. Ordered by posted_at ASC, ties by the
    # Payment.created_at ASC (then internal seq for full determinism).
    events = []
    for payment in db.payments.values():
        if payment["status"] != "POSTED":
            continue
        posted_at = payment["posted_at"]
        if posted_at is None:
            continue
        if not (promo_start <= posted_at < promo_end):
            continue
        principal_applied = 0
        for line in payment["allocation"]:
            if line["financed_purchase_id"] == purchase["id"]:
                principal_applied += line["principal_applied_cents"]
        if principal_applied > 0:
            events.append((posted_at, payment["created_at"], payment["_seq"], principal_applied))

    events.sort(key=lambda e: (e[0], e[1], e[2]))

    outstanding = purchase["principal_cents"]
    accrued = 0.0
    prev_t = promo_start
    for posted_at, _c, _s, principal_applied in events:
        days = whole_days(prev_t, posted_at)
        accrued += outstanding * daily_rate * days
        outstanding -= principal_applied
        prev_t = posted_at
    accrued += outstanding * daily_rate * whole_days(prev_t, promo_end)
    return round_half_up(accrued)


def projected_forfeit_interest(purchase, current_clock):
    """Forward-looking projection (advisory, never posted).

    Charges full promo_apr on the entire remaining principal for the whole
    window still remaining (whole days from now to promo_end).
    """
    plan = _plan_for_purchase(purchase)
    promo_apr = plan["promo_apr"]
    daily_rate = promo_apr / DAYS_PER_YEAR
    principal_remaining = purchase["principal_cents"] - purchase["principal_paid_cents"]
    days_remaining = whole_days(current_clock, purchase["promo_end"])
    projected = round_half_up(principal_remaining * daily_rate * days_remaining)
    return projected, principal_remaining, days_remaining
