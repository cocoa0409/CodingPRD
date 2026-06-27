"""Calculation rules (PRD §2.6, §3.9, §3.10, §3.11; scaffold §1.3).

All money is integer cents, all rates are integer basis points (10,000 bps =
100%). Interest is SIMPLE interest over whole elapsed days. Each interest
component is rounded to whole cents with ROUND_HALF_UP first, and only then are
the rounded components summed (per-component-then-sum, never sum-then-round).
"""
from decimal import Decimal, ROUND_HALF_UP

SECONDS_PER_DAY = 86400


def floor_days(start_dt, end_dt):
    """Whole elapsed days between two logical-clock instants (floor).

    Partial days never accrue; day zero accrues nothing. Redeeming exactly
    issued_at + k*86400 seconds yields k days; one second earlier yields k-1.
    """
    delta = (end_dt - start_dt).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // SECONDS_PER_DAY)


def _round_half_up(numerator):
    """Round a Decimal to whole cents using round-half-up."""
    return int(Decimal(numerator).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def simple_interest(principal_cents, rate_bps, days, day_count_basis):
    """One interest component, rounded to whole cents (round-half-up).

    principal * rate_bps * days / (10000 * day_count_basis).
    """
    if days <= 0 or principal_cents <= 0 or rate_bps <= 0:
        return 0
    numerator = Decimal(principal_cents) * Decimal(rate_bps) * Decimal(days)
    denominator = Decimal(10000) * Decimal(day_count_basis)
    return _round_half_up(numerator / denominator)


def flat_penalty(face_amount_cents, penalty_rate_bps):
    """Flat penalty = round_half_up(face * penalty_rate_bps / 10000)."""
    if penalty_rate_bps <= 0 or face_amount_cents <= 0:
        return 0
    numerator = Decimal(face_amount_cents) * Decimal(penalty_rate_bps)
    return _round_half_up(numerator / Decimal(10000))


def compute_payoff(county, certificate, posted_sub_taxes, as_of_dt,
                   filed_deed_cost_cents=0):
    """Full redemption/payoff math (PRD §3.9).

    posted_sub_taxes: list of POSTED SubsequentTax records in posting order.
    Returns a dict with each component plus total_payoff_cents.
    """
    basis = county["day_count_basis"]
    face = certificate["face_amount_cents"]
    rate_bps = certificate["rate_bps"]

    face_days = floor_days(certificate["issued_at_dt"], as_of_dt)
    face_interest = simple_interest(face, rate_bps, face_days, basis)
    penalty = flat_penalty(face, county["penalty_rate_bps"])

    # Sub-tax: round per sub-tax, then sum (pinned posting order).
    sub_tax_payoff = 0
    sub_tax_interest = 0
    for st in posted_sub_taxes:
        sub_tax_payoff += st["principal_cents"]
        st_days = floor_days(st["posted_at_dt"], as_of_dt)
        sub_tax_interest += simple_interest(
            st["principal_cents"], county["sub_tax_interest_rate_bps"], st_days, basis
        )

    # Premium refund: premium + interest on premium when premium_earns_interest.
    if county["premium_earns_interest"]:
        prem = certificate["premium_cents"]
        prem_interest = simple_interest(prem, rate_bps, face_days, basis)
        premium_refund = prem + prem_interest
    else:
        premium_refund = 0

    total = (
        face
        + face_interest
        + penalty
        + sub_tax_payoff
        + sub_tax_interest
        + premium_refund
        + filed_deed_cost_cents
    )

    return {
        "face_payoff_cents": face,
        "face_interest_cents": face_interest,
        "penalty_cents": penalty,
        "sub_tax_payoff_cents": sub_tax_payoff,
        "sub_tax_interest_cents": sub_tax_interest,
        "premium_refund_cents": premium_refund,
        "filed_deed_cost_cents": filed_deed_cost_cents,
        "total_payoff_cents": total,
    }


def compute_position(county, certificate, posted_sub_taxes, as_of_dt, deed_cost_cents):
    """Full lien position + deed cost = minimum_bid_cents (PRD §3.10).

    Identical accrual to redemption but WITHOUT premium refund. Frozen at filing.
    """
    basis = county["day_count_basis"]
    face = certificate["face_amount_cents"]
    rate_bps = certificate["rate_bps"]

    face_days = floor_days(certificate["issued_at_dt"], as_of_dt)
    face_interest = simple_interest(face, rate_bps, face_days, basis)
    penalty = flat_penalty(face, county["penalty_rate_bps"])

    sub_tax_principal = 0
    sub_tax_interest = 0
    for st in posted_sub_taxes:
        sub_tax_principal += st["principal_cents"]
        st_days = floor_days(st["posted_at_dt"], as_of_dt)
        sub_tax_interest += simple_interest(
            st["principal_cents"], county["sub_tax_interest_rate_bps"], st_days, basis
        )

    position = face + face_interest + penalty + sub_tax_principal + sub_tax_interest
    return position + deed_cost_cents


def compute_surplus(gross_proceeds_cents, minimum_bid_cents):
    """Waterfall: holder bucket filled first, overage to former owner (PRD §3.11)."""
    lien_satisfied = min(gross_proceeds_cents, minimum_bid_cents)
    surplus = max(0, gross_proceeds_cents - minimum_bid_cents)
    return lien_satisfied, surplus
