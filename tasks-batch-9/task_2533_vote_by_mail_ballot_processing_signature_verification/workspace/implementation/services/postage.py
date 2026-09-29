"""Postage assessment (PRD 2.8 / 3.3). Whole cents, round-half-up per packet."""
import math
from decimal import ROUND_HALF_UP, Decimal

from constants import (
    FORWARDING_ENDORSEMENT_CENTS,
    POSTAGE_OVERWEIGHT_STEP_CENTS,
    POSTAGE_OVERWEIGHT_STEP_GRAMS,
    POSTAGE_TIER_1_CENTS,
    POSTAGE_TIER_1_MAX_GRAMS,
    POSTAGE_TIER_2_CENTS,
    POSTAGE_TIER_2_MAX_GRAMS,
    POSTAGE_TIER_3_CENTS,
    POSTAGE_TIER_3_MAX_GRAMS,
    RETURN_POSTAGE_PREPAID_CENTS,
    UOCAVA_SURCHARGE_RATE,
)


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def outbound_cents(grams):
    if grams <= POSTAGE_TIER_1_MAX_GRAMS:
        return POSTAGE_TIER_1_CENTS
    if grams <= POSTAGE_TIER_2_MAX_GRAMS:
        return POSTAGE_TIER_2_CENTS
    if grams <= POSTAGE_TIER_3_MAX_GRAMS:
        return POSTAGE_TIER_3_CENTS
    excess = grams - POSTAGE_TIER_3_MAX_GRAMS
    steps = int(math.ceil(Decimal(excess) / Decimal(POSTAGE_OVERWEIGHT_STEP_GRAMS)))
    return POSTAGE_TIER_3_CENTS + POSTAGE_OVERWEIGHT_STEP_CENTS * steps


def packet_postage_cents(grams, uocava_status, forwarding_class):
    outbound = outbound_cents(grams)
    if uocava_status != "NONE":
        surcharge = round_half_up_cents(Decimal(outbound) * UOCAVA_SURCHARGE_RATE)
    else:
        surcharge = 0
    endorsement = (
        FORWARDING_ENDORSEMENT_CENTS if forwarding_class == "FORWARDABLE" else 0
    )
    return outbound + surcharge + endorsement + RETURN_POSTAGE_PREPAID_CENTS


def batch_total_cents(packets):
    """Sum of the already-rounded per-packet figures -- never a re-rounded aggregate."""
    return sum(p["packet_postage_cents"] for p in packets)
