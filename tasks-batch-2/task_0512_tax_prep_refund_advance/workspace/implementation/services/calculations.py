"""Calculation rules (SCAFFOLD Table 3, PRD §3.4, §3.7, §3.8). All money in
integer cents. Rounding is half-up; evaluation orders are PINNED as written in
the PRD and must not be reordered for convenience."""
from decimal import Decimal

import constants
from money import D, round_half_up


# ---------------------------------------------------------------------------
# prep_fee_total (PRD §3.4) — written to TaxReturn.prep_fee_cents and
# materialized as FeeLine rows. Round-per-line, not sum-then-round.
# Returns (prep_fee_cents, [ (line_kind, label, amount_cents), ... ]).
# ---------------------------------------------------------------------------
def prep_fee_total(complexity_band, schedules, state_return_count, is_returning):
    mult = D(constants.BAND_MULT[complexity_band])

    lines = []

    # Base 1040 line — rounded half-up to whole cents.
    base_line = round_half_up(D(constants.BASE_1040_CENTS) * mult)
    lines.append(("BASE_1040", "Base 1040", base_line))

    # One SCHEDULE line per attached schedule, rounded individually.
    sched_total = 0
    for s in schedules:
        amt = round_half_up(D(constants.SCHEDULE_FEE[s]) * mult)
        lines.append(("SCHEDULE", "Schedule %s" % s, amt))
        sched_total += amt

    # One STATE_RETURN line per state return, rounded individually.
    state_total = 0
    for _ in range(state_return_count):
        amt = round_half_up(D(constants.STATE_RETURN_CENTS) * mult)
        lines.append(("STATE_RETURN", "State return", amt))
        state_total += amt

    subtotal = base_line + sched_total + state_total

    # Returning-client discount: only when is_returning. min(cap, pct*subtotal),
    # discount rounded after the subtotal is formed. A single negative line.
    if is_returning:
        discount = min(
            constants.DISCOUNT_CAP_CENTS,
            round_half_up(D(subtotal) * D(constants.DISCOUNT_PCT)),
        )
        if discount > 0:
            lines.append(("DISCOUNT", "Returning-client discount", -discount))
        prep_fee_cents = max(0, subtotal - discount)
    else:
        prep_fee_cents = subtotal

    return prep_fee_cents, lines


# ---------------------------------------------------------------------------
# advance_max_eligible (PRD §3.8) — nested min over a refund-size tier cap and a
# risk-band fraction of the expected refund. Fraction product rounded half-up.
# ---------------------------------------------------------------------------
def advance_max_eligible(expected_refund_cents, risk_band):
    tier_cap = constants.advance_tier_cap(expected_refund_cents)
    fraction = D(constants.RISK_FRACTION[risk_band])
    fraction_product = round_half_up(D(expected_refund_cents) * fraction)
    return min(tier_cap, fraction_product)


# ---------------------------------------------------------------------------
# refund_disbursement_waterfall (PRD §3.7) — distribute disbursed refund across
# four ordered buckets; each takes min(remaining, owed). Pinned order.
# Returns dict with net_to_taxpayer_cents, fee_shortfall_cents, total_fees,
# per-bucket takes, and the electronic-disbursement surcharge.
# ---------------------------------------------------------------------------
def refund_disbursement_waterfall(disbursed_refund_cents, bank_product_fee,
                                  prep_fee, audit_fee, advance_repay_owed):
    buckets = [
        ("bank_product_fee", bank_product_fee),
        ("prep_fee", prep_fee),
        ("audit_fee", audit_fee),
        ("advance_repay", advance_repay_owed),
    ]

    remaining = disbursed_refund_cents
    takes = {}
    for name, amount in buckets:
        take = min(remaining, amount)
        takes[name] = take
        remaining -= take

    net_to_taxpayer_cents = remaining
    total_fees = bank_product_fee + prep_fee + audit_fee + advance_repay_owed
    fee_shortfall_cents = max(0, total_fees - disbursed_refund_cents)

    # disbursement_surcharge (PRD §3.7): 2.9% of each funded bucket (take > 0),
    # rounded half-up per bucket BEFORE summing (round-per-bucket-then-sum).
    surcharge = 0
    pct = D(constants.SURCHARGE_PCT)
    for name, _amount in buckets:
        take = takes[name]
        if take > 0:
            surcharge += round_half_up(D(take) * pct)

    return {
        "net_to_taxpayer_cents": net_to_taxpayer_cents,
        "fee_shortfall_cents": fee_shortfall_cents,
        "total_fees": total_fees,
        "takes": takes,
        "surcharge_cents": surcharge,
    }
