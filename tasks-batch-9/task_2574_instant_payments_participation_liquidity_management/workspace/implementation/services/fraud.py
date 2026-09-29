"""Fraud scoring: the origination variant and the review-final variant."""

from decimal import Decimal, ROUND_HALF_UP

from services import limits
from services.constants import (
    AMOUNT_TERM_CAP,
    AMOUNT_UNIT_CENTS,
    AMOUNT_WEIGHT,
    FINAL_VELOCITY_WINDOW_MINUTES,
    NEW_BENEFICIARY_BONUS,
    SEGMENT_MULTIPLIER,
    VELOCITY_FREE_COUNT_FINAL,
    VELOCITY_FREE_COUNT_ORIGINATION,
    VELOCITY_WEIGHT_FINAL,
    VELOCITY_WEIGHT_ORIGINATION,
    VELOCITY_WINDOW_MINUTES,
)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _score(base, amount_cents, window_count, weight, free, new_beneficiary, segment):
    amount_term = AMOUNT_WEIGHT * min(AMOUNT_TERM_CAP, amount_cents // AMOUNT_UNIT_CENTS)
    velocity_term = weight * max(0, window_count - free)
    beneficiary_term = NEW_BENEFICIARY_BONUS if new_beneficiary else 0
    raw = base + amount_term + velocity_term + beneficiary_term
    multiplier = SEGMENT_MULTIPLIER[segment]
    scaled = round_half_up(Decimal(raw) * multiplier)
    return min(100, scaled), amount_term, velocity_term, beneficiary_term


def reason_codes(base, amount_term, velocity_term, beneficiary_term):
    codes = []
    if base >= 40:
        codes.append("BASELINE_RISK")
    if amount_term > 0:
        codes.append("AMOUNT_BAND")
    if velocity_term > 0:
        codes.append("VELOCITY_BURST")
    if beneficiary_term > 0:
        codes.append("NEW_BENEFICIARY")
    return codes


def score_at_origination(customer_account, amount_cents, receiver_routing_number, window_count):
    base = customer_account["fraud_risk_baseline"]
    new_beneficiary = not limits.has_settled_beneficiary(
        customer_account["id"], receiver_routing_number
    )
    score, amount_term, velocity_term, beneficiary_term = _score(
        base,
        amount_cents,
        window_count,
        VELOCITY_WEIGHT_ORIGINATION,
        VELOCITY_FREE_COUNT_ORIGINATION,
        new_beneficiary,
        customer_account["segment"],
    )
    return score, reason_codes(base, amount_term, velocity_term, beneficiary_term)


def score_at_review(customer_account, transfer):
    """The REVIEW_FINAL variant: weight 3, free 5, 1,440-minute window."""
    base = customer_account["fraud_risk_baseline"]
    window_count = len(limits.velocity_rows(
        customer_account["id"],
        FINAL_VELOCITY_WINDOW_MINUTES,
        exclude_transfer_id=transfer["id"],
    ))
    new_beneficiary = not limits.has_settled_beneficiary(
        customer_account["id"],
        transfer["receiver_routing_number"],
        exclude_transfer_id=transfer["id"],
    )
    score, _amount_term, _velocity_term, _beneficiary_term = _score(
        base,
        transfer["amount_cents"],
        window_count,
        VELOCITY_WEIGHT_FINAL,
        VELOCITY_FREE_COUNT_FINAL,
        new_beneficiary,
        customer_account["segment"],
    )
    return score


def origination_window_count(customer_account_id):
    return len(limits.velocity_rows(customer_account_id, VELOCITY_WINDOW_MINUTES))
