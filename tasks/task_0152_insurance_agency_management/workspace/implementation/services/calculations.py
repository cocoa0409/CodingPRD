"""Money calculations (PRD §3.5, §3.6, §3.10 / SCAFFOLD §1.3).

All money is integer cents; rounding is round-half-up applied once per declared
step. We use Decimal everywhere to avoid float error.
"""
from decimal import Decimal

from db import store
from util import round_half_up, days_between, parse_dt

SHORT_RATE_PENALTY = Decimal("0.10")

TIER1_CEIL_CENTS = 100000   # < 100000 -> 1.00
TIER2_CEIL_CENTS = 500000   # [100000, 500000) -> 1.05; >= 500000 -> 1.10
TIER1_MULT = Decimal("1.00")
TIER2_MULT = Decimal("1.05")
TIER3_MULT = Decimal("1.10")


# --- return premium (§3.6) -------------------------------------------------

def compute_return_premium(policy, product):
    """Return (return_premium_cents, earned_premium_cents) for a cancellation.

    effective_basis = PRO_RATA when cancellation_reason == NON_PAYMENT,
    else Product.cancellation_basis. Rounding applied once at the end of the
    chosen branch.
    """
    eff = parse_dt(policy["effective_date"], "effective_date")
    exp = parse_dt(policy["expiration_date"], "expiration_date")
    cancel = parse_dt(policy["cancellation_date"], "cancellation_date")

    term_days = days_between(eff, exp)
    unearned_days = days_between(cancel, exp)

    annual = Decimal(policy["annual_premium_cents"])

    if policy["cancellation_reason"] == "NON_PAYMENT":
        basis = "PRO_RATA"
    else:
        basis = product["cancellation_basis"]

    pro_rata = annual * Decimal(unearned_days) / Decimal(term_days)
    if basis == "PRO_RATA":
        return_premium = round_half_up(pro_rata)
    else:  # SHORT_RATE
        return_premium = round_half_up(pro_rata * (Decimal(1) - SHORT_RATE_PENALTY))

    earned = policy["annual_premium_cents"] - return_premium
    return return_premium, earned


# --- producer commission accrual (§3.5) ------------------------------------

def _tier_multiplier(annual_premium_cents):
    if annual_premium_cents < TIER1_CEIL_CENTS:
        return TIER1_MULT
    if annual_premium_cents < TIER2_CEIL_CENTS:
        return TIER2_MULT
    return TIER3_MULT


def agency_commission_cents(policy):
    """Post-tier agency commission for a policy (steps 1-3 of §3.5).

    Step 1: base rate by term_kind, Product override else Carrier default.
    Step 2: round_half_up(annual * base_rate).
    Step 3: multiply by tier multiplier, round_half_up again.
    """
    product = store.products[policy["product_id"]]
    carrier = store.carriers[product["carrier_id"]]

    if policy["term_kind"] == "NEW_BUSINESS":
        rate = product["new_business_commission_pct"]
        if rate is None:
            rate = carrier["default_new_business_commission_pct"]
    else:  # RENEWAL
        rate = product["renewal_commission_pct"]
        if rate is None:
            rate = carrier["default_renewal_commission_pct"]

    annual = Decimal(policy["annual_premium_cents"])
    base = round_half_up(annual * Decimal(str(rate)))

    mult = _tier_multiplier(policy["annual_premium_cents"])
    post_tier = round_half_up(Decimal(base) * mult)
    return post_tier


def split_accrual_cents(policy, split):
    """Per-split producer accrual (step 4 of §3.5): post-tier agency commission
    * split_pct, rounded half-up per line."""
    agency = Decimal(agency_commission_cents(policy))
    return round_half_up(agency * Decimal(str(split["split_pct"])))


# --- commission statement rollup (§3.10) -----------------------------------

def compute_statement_figures(statement):
    """Live recompute of (gross, chargeback, net) for an OPEN statement.

    gross: sum of per-line accrual over the producer's LOCKED splits whose
    policy activated within [period_start, period_end).
    chargeback: sum over the producer's splits on policies cancelled within the
    window, of round_half_up(accrual * return_premium/annual), per policy line.
    net = gross - chargeback.
    """
    period_start = parse_dt(statement["period_start"], "period_start")
    period_end = parse_dt(statement["period_end"], "period_end")
    producer_id = statement["producer_id"]

    gross = 0
    chargeback = 0

    for split in store.commission_splits.values():
        if split["producer_id"] != producer_id:
            continue
        if split["status"] != "LOCKED":
            continue
        policy = store.policies.get(split["policy_id"])
        if policy is None:
            continue

        # gross: activation timestamp in window
        activated_at = policy.get("activated_at")
        if activated_at is not None:
            act_dt = parse_dt(activated_at, "activated_at")
            if period_start <= act_dt < period_end:
                gross += split_accrual_cents(policy, split)

        # chargeback: cancelled in window with a return premium
        if policy["status"] == "CANCELLED" and policy.get("cancellation_date"):
            cancel_dt = parse_dt(policy["cancellation_date"], "cancellation_date")
            if period_start <= cancel_dt < period_end:
                annual = policy["annual_premium_cents"]
                if annual:
                    accrual = Decimal(split_accrual_cents(policy, split))
                    frac = Decimal(policy["return_premium_cents"]) / Decimal(annual)
                    chargeback += round_half_up(accrual * frac)

    net = gross - chargeback
    return gross, chargeback, net
