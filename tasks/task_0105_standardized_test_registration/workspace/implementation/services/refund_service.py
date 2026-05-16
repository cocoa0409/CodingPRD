"""Tiered refund computation (§3.8)."""

from datetime import timedelta
from decimal import Decimal

import db
from clock import now
from config import (
    FULL_TIER_THRESHOLD_DAYS,
    PARTIAL_50_TIER_THRESHOLD_DAYS,
    PARTIAL_75_TIER_THRESHOLD_DAYS,
)
from money import round_half_up_cents
from response import parse_iso_utc


def _pick_tier(days_before_test: int) -> tuple:
    """Return (tier_label, rate_decimal)."""
    if days_before_test >= FULL_TIER_THRESHOLD_DAYS:
        return "FULL", Decimal("1.00")
    if days_before_test >= PARTIAL_75_TIER_THRESHOLD_DAYS:
        return "PARTIAL_75", Decimal("0.75")
    if days_before_test >= PARTIAL_50_TIER_THRESHOLD_DAYS:
        return "PARTIAL_50", Decimal("0.50")
    return "NONE", Decimal("0.00")


def compute_refund_and_record(*, registration: dict, test_event: dict, channel: str) -> dict:
    """Compute the refund and append a RefundTransaction. Mutates registration in place."""
    test_date = parse_iso_utc(test_event["test_date"])
    current_now = now()
    delta_seconds = (test_date - current_now).total_seconds()
    days_before_test = int(delta_seconds // 86400)

    tier_label, time_rate = _pick_tier(days_before_test)

    # The recorded tier_label is the actual time-tier at cancellation, regardless
    # of the channel forcing the rate to FULL in OFFICIAL_CANCELLATION.
    if channel == "OFFICIAL_CANCELLATION":
        effective_rate = Decimal("1.00")
    else:
        effective_rate = time_rate

    refund_base = round_half_up_cents(registration["base_fee_cents_charged"], effective_rate)
    refund_late = round_half_up_cents(registration["late_fee_cents_charged"], effective_rate)
    refund_accommodation = 0  # Always non-refundable
    candidate_refund = refund_base + refund_late + refund_accommodation
    amount_cents = max(0, candidate_refund)

    tx = build_refund_transaction(
        registration_id=registration["id"],
        amount_cents=amount_cents,
        tier_label=tier_label,
        refund_channel=channel,
    )
    db.refund_transactions.insert(tx)

    # Recompute amount_refunded_cents / amount_retained_cents
    total_refunded = sum(
        t["amount_cents"] for t in db.refund_transactions.all() if t["registration_id"] == registration["id"]
    )
    registration["amount_refunded_cents"] = total_refunded
    registration["amount_retained_cents"] = registration["amount_charged_cents"] - total_refunded
    db.touch(registration)
    return tx


def build_refund_transaction(*, registration_id: str, amount_cents: int, tier_label: str, refund_channel: str) -> dict:
    tx = db.append_create()
    tx.update(
        {
            "registration_id": registration_id,
            "amount_cents": amount_cents,
            "tier_label": tier_label,
            "refund_channel": refund_channel,
        }
    )
    return tx
