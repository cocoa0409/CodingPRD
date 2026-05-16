"""Domain thresholds and numeric constants from PRD §2 and §3.

Quoted PRD prose anchors each constant below.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Time / day thresholds (PRD §3.4, §3.6, §3.7, §3.8, §3.9)
# ---------------------------------------------------------------------------
THRESHOLDS = {
    # PRD §3.4: "the system computes the closed interval from
    # `test_date - 4 hours` through `test_date + 4 hours + 4 hours`" —
    # the four-hour test-session window padded by a four-hour cooldown.
    "TEST_SESSION_HOURS": 4,
    "CANDIDATE_COOLDOWN_HOURS": 4,
    # PRD §3.7: "the window from `test_date - 2 hours` to
    # `test_date + 1 hour` (check-in opens two hours before the
    # scheduled start and closes one hour after)"
    "CHECK_IN_WINDOW_HOURS": 2,
    "CHECK_IN_GRACE_HOURS": 1,
    # PRD §3.6: "`submission_deadline_at` is fourteen days before the
    # event's `registration_deadline`, and `review_deadline_at` is
    # `submission_deadline_at` plus seven days"
    "ACCOMMODATION_LEAD_DAYS": 14,
    "ACCOMMODATION_REVIEW_WINDOW_DAYS": 7,
    # PRD §3.9: "Sittings whose `TestEvent.test_date` is more than
    # 730 days (24 months) before `as_of_date` are excluded from the pool"
    "SUPER_SCORE_LOOKBACK_DAYS": 730,
    # PRD §3.8 refund tier thresholds.
    "FULL_TIER_THRESHOLD_DAYS": 30,
    "PARTIAL_75_TIER_THRESHOLD_DAYS": 15,
    "PARTIAL_50_TIER_THRESHOLD_DAYS": 7,
    # PRD §3.4: "`accommodation_fee_cents_charged` is 2500 cents when
    # `accommodation_required` is true at creation and zero otherwise"
    "ACCOMMODATION_FEE_CENTS": 2500,
    # PRD §3.4: "`standby_promotion_eligibility_at` is set to
    # `registered_at` plus the standby visibility delay (a value the
    # system pins at zero seconds so promotion eligibility is
    # effectively immediate)"
    "STANDBY_VISIBILITY_DELAY_SECONDS": 0,
    # PRD §2.4 / §2.7 — version semantics
    "INITIAL_VERSION": 1,
}


# ---------------------------------------------------------------------------
# Refund tier table (PRD §3.8)
# ---------------------------------------------------------------------------
# PRD §3.8: "when `days_before_test` is at least 30 the tier is `FULL`
# with a rate of 1.00; when `days_before_test` is at least 15 and less
# than 30 the tier is `PARTIAL_75` with a rate of 0.75; when
# `days_before_test` is at least 7 and less than 15 the tier is
# `PARTIAL_50` with a rate of 0.50; and when `days_before_test` is less
# than 7 the tier is `NONE` with a rate of 0.00."
def refund_tier_for_days(days_before_test: int) -> tuple[str, float]:
    """Return (tier_label, rate) per PRD §3.8 thresholds."""
    if days_before_test >= 30:
        return "FULL", 1.00
    if days_before_test >= 15:
        return "PARTIAL_75", 0.75
    if days_before_test >= 7:
        return "PARTIAL_50", 0.50
    return "NONE", 0.00


# ---------------------------------------------------------------------------
# CLEP credit lookups (PRD §3.10)
# ---------------------------------------------------------------------------
# PRD §3.10: "The recommended-score table assigns 50 to each of the
# five recognised subjects above"
ACE_RECOMMENDED_SCORE_BY_SUBJECT = {
    "CLEP_COLLEGE_ALGEBRA": 50,
    "CLEP_AMERICAN_GOVERNMENT": 50,
    "CLEP_BIOLOGY": 50,
    "CLEP_CHEMISTRY": 50,
    "CLEP_COLLEGE_COMPOSITION": 50,
}

# PRD §3.10: "the credit-units table assigns 3 units to
# `CLEP_COLLEGE_ALGEBRA` and `CLEP_AMERICAN_GOVERNMENT`, and 6 units
# to `CLEP_BIOLOGY`, `CLEP_CHEMISTRY`, and `CLEP_COLLEGE_COMPOSITION`"
CLEP_CREDIT_UNITS_BY_SUBJECT = {
    "CLEP_COLLEGE_ALGEBRA": 3,
    "CLEP_AMERICAN_GOVERNMENT": 3,
    "CLEP_BIOLOGY": 6,
    "CLEP_CHEMISTRY": 6,
    "CLEP_COLLEGE_COMPOSITION": 6,
}


# ---------------------------------------------------------------------------
# Helper: round half up to integer cents (PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up_to_int(value: float) -> int:
    """Round half-up to nearest integer.

    PRD §2.6: "Wherever a calculation multiplies a cents amount by a
    rate, the resulting product is rounded half-up (standard banker-
    independent commercial rounding) to the nearest whole cent before
    being used downstream."
    """
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


# ---------------------------------------------------------------------------
# PRD §3.8 per-line rounded refund — used by tests to verify the
# pinned round-then-sum order is observable on RefundTransaction.amount_cents.
# ---------------------------------------------------------------------------
def per_line_refund_cents(base_fee_cents: int, late_fee_cents: int,
                          rate: float) -> int:
    """Per-line rounded refund per PRD §3.8.

    PRD §3.8: "the refund on the base fee is `base_fee_cents_charged`
    multiplied by the rate (rounded half-up); the refund on the late
    fee is `late_fee_cents_charged` multiplied by the rate (rounded
    half-up); the refund on the accommodation fee is always zero, ...
    The candidate refund is the sum of those three rounded line
    amounts."
    """
    refund_base = round_half_up_to_int(base_fee_cents * rate)
    refund_late = round_half_up_to_int(late_fee_cents * rate)
    return refund_base + refund_late


# ---------------------------------------------------------------------------
# Test defaults used by factories and fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "INITIAL_CLOCK": "2026-01-01T00:00:00.000Z",
    "DEFAULT_BASE_FEE_CENTS": 6000,
    "DEFAULT_LATE_FEE_CENTS": 2000,
    "DEFAULT_TOTAL_CAPACITY": 10,
    "DEFAULT_ACCOMMODATION_CAPACITY": 2,
    "DEFAULT_STATE_CODE": "CA",
    "DEFAULT_TIMEZONE": "America/Los_Angeles",
}


__all__ = [
    "THRESHOLDS",
    "ACE_RECOMMENDED_SCORE_BY_SUBJECT",
    "CLEP_CREDIT_UNITS_BY_SUBJECT",
    "refund_tier_for_days",
    "round_half_up_to_int",
    "per_line_refund_cents",
    "TEST_DEFAULTS",
]
