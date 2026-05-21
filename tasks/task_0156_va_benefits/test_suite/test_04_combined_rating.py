"""Combined-rating computation — PRD §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_claim,
    create_veteran,
    deny_claim_for_veteran,
    get_veteran,
    grant_claim_for_veteran,
    make_rater_headers,
    reopen_claim,
    start_review_claim,
    grant_claim,
    validate_success,
)


class TestCombinedRatingZeroCases:

    def test_veteran_with_no_claims_has_combined_rating_zero(self, api):
        """PRD §3.4: "Its inputs are the granted ratings of every claim
        belonging to this veteran whose status is currently GRANTED ...
        It begins with a remaining-efficiency factor of 1.0, and for
        each rating r in the sorted list it multiplies the
        remaining-efficiency factor by (1.0 minus r divided by 100.0).
        After every rating has been folded in, the raw combined value
        is (1.0 minus the remaining-efficiency factor) multiplied by
        100.0".

        Empty input -> remaining_efficiency stays at 1.0 -> raw == 0.

        # difficulty: boundary_precision_check/empty_claims_set_combined_rating_zero
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        assert vet["combined_rating"] == 0

    def test_veteran_with_only_denied_claim_has_combined_rating_zero(
        self, api,
    ):
        """PRD §3.4: "claims in SUBMITTED, UNDER_REVIEW, DENIED,
        APPEALED, or DENIED_FINAL are excluded."

        # difficulty: boundary_precision_check/empty_claims_set_combined_rating_zero
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        deny_claim_for_veteran(vet["id"])
        refreshed = get_veteran(vet["id"])
        assert refreshed["combined_rating"] == 0, (
            "DENIED claim must be excluded from input set"
        )


class TestCombinedRatingComputation:

    def test_single_granted_40_yields_combined_40(self, api):
        """PRD §3.4: "remaining_efficiency by (1.0 minus r divided by
        100.0) ... raw combined value is (1.0 minus the
        remaining-efficiency factor) multiplied by 100.0 ... This raw
        value is then rounded half-up to the nearest whole percent; the
        resulting integer is then divided by 10, rounded half-up to the
        nearest integer, and multiplied by 10".

        Single rating 40: 1 - 0.6 = 0.4 -> 40 -> nearest 10 = 40.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        grant_claim_for_veteran(vet["id"], granted_rating=40)
        refreshed = get_veteran(vet["id"])
        assert refreshed["combined_rating"] == 40

    def test_two_grants_40_and_20_yields_combined_50(self, api):
        """PRD §3.4: "It begins with a remaining-efficiency factor of
        1.0, and for each rating r in the sorted list it multiplies
        the remaining-efficiency factor by (1.0 minus r divided by
        100.0). After every rating has been folded in, the raw
        combined value is (1.0 minus the remaining-efficiency factor)
        multiplied by 100.0".

        Two ratings 40 and 20: 1.0 * 0.6 * 0.8 = 0.48 -> 52 -> nearest
        10 = 50.

        # difficulty: dual_variant_calc/claim_combined_rating_pre_vs_post_reopen
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        grant_claim_for_veteran(
            vet["id"], granted_rating=40, starter_rater_id="rater-A",
        )
        grant_claim_for_veteran(
            vet["id"], granted_rating=20, starter_rater_id="rater-B",
        )
        refreshed = get_veteran(vet["id"])
        # 1 - 0.6*0.8 = 0.52 -> 52 -> round half-up to nearest 10 = 50.
        assert refreshed["combined_rating"] == 50

    def test_reopen_excludes_claim_from_input_set(self, api):
        """PRD §3.4: "Its inputs are the granted ratings of every claim
        belonging to this veteran whose status is currently GRANTED —
        claims in SUBMITTED, UNDER_REVIEW, DENIED, APPEALED, or
        DENIED_FINAL are excluded."

        Two GRANTED claims (40, 20) -> combined 50. Reopen the 20 ->
        only the 40 remains GRANTED -> combined 40.

        # difficulty: dual_variant_calc/claim_combined_rating_pre_vs_post_reopen
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        grant_claim_for_veteran(
            vet["id"], granted_rating=40, starter_rater_id="rater-A",
        )
        twenty = grant_claim_for_veteran(
            vet["id"], granted_rating=20, starter_rater_id="rater-B",
        )
        # Reopen by a third rater so segregation passes (rater_id == B
        # on the 20 claim).
        reopen_claim(twenty["id"], rater_operator_id="rater-C")
        refreshed = get_veteran(vet["id"])
        # Only the 40 claim is still GRANTED -> combined_rating = 40.
        assert refreshed["combined_rating"] == 40


class TestCombinedRatingHigherRated:

    def test_two_grants_50_and_30_yields_combined_70(self, api):
        """PRD §3.4: process descending, multiply (1 - r/100): 1 * 0.5
        * 0.7 = 0.35 -> raw 65 -> nearest 10 (half-up) = 70.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        grant_claim_for_veteran(
            vet["id"], granted_rating=50, starter_rater_id="rater-A",
        )
        grant_claim_for_veteran(
            vet["id"], granted_rating=30, starter_rater_id="rater-B",
        )
        refreshed = get_veteran(vet["id"])
        # 1 - 0.5 * 0.7 = 0.65 -> 65 -> nearest 10 half-up = 70.
        assert refreshed["combined_rating"] == 70

    def test_combined_rating_clamped_to_100(self, api):
        """PRD §3.4: "The final figure is clamped into the inclusive
        range from 0 to 100".

        Three rating-100 grants would never push above 100 mathematically,
        but verify a single rating 100 lands at 100.
        """
        vet = create_veteran(aggregate_active_duty_days=1100)
        grant_claim_for_veteran(vet["id"], granted_rating=100)
        refreshed = get_veteran(vet["id"])
        assert refreshed["combined_rating"] == 100
