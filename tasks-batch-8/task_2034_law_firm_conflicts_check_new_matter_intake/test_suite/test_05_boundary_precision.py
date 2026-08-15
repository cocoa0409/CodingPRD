"""Boundary precision: credit-band thresholds and retainer funding equality."""
from test_helpers import (
    TEST_USERS,
    api_client,
    fund_deposit,
    record_credit_assessment,
    setup_basic_matter,
    setup_matter_with_issued_letter,
    transition_deposit_payload,
    validate_success,
)

BILLING = TEST_USERS["billing_clerk_headers"]


class TestCreditBandBoundary740Inclusive:
    def test_score_740_is_prime(self):
        """PRD §3.8: "The server stamps `assessed_at` from the logical clock and
        derives the `band`: `PRIME` when the score is at least 740, `STANDARD`
        from 670 through 739, and `SUBPRIME` below 670 — so 740 is `PRIME`, 739
        is `STANDARD`, 670 is `STANDARD`, and 669 is `SUBPRIME`."

        Design: Difficulty/boundary_precision_check/credit_band_boundary_740_inclusive
        """
        _, _, matter = setup_basic_matter("Boundary Client Inc")
        assessment = record_credit_assessment(matter["id"], 740)
        assert assessment["band"] == "PRIME", (
            f"inclusive threshold: >= 740 is PRIME; got {assessment['band']}"
        )

    def test_score_739_is_standard(self):
        """PRD §3.8: "The server stamps `assessed_at` from the logical clock and
        derives the `band`: `PRIME` when the score is at least 740, `STANDARD`
        from 670 through 739, and `SUBPRIME` below 670 — so 740 is `PRIME`, 739
        is `STANDARD`, 670 is `STANDARD`, and 669 is `SUBPRIME`."

        Design: Difficulty/boundary_precision_check/credit_band_boundary_740_inclusive
        """
        _, _, matter = setup_basic_matter("Boundary Client Inc")
        assessment = record_credit_assessment(matter["id"], 739)
        assert assessment["band"] == "STANDARD", (
            f"one point below flips the band; got {assessment['band']}"
        )


class TestRetainerExactEqualityFunded:
    def test_one_cent_short_of_required_is_partially_funded(self):
        """PRD §3.8: "The deposit's `status` is re-derived after every mutation:
        `PENDING` when nothing is held, `PARTIALLY_FUNDED` when the held balance
        is greater than zero but below the requirement, and `FUNDED` when the
        held balance is greater than or equal to the requirement — equality
        counts as funded."

        Design: Difficulty/boundary_precision_check/retainer_exact_equality_funded
        """
        _, _, matter, _, deposit = setup_matter_with_issued_letter(
            "Equality Client Inc"
        )
        assert deposit["required_cents"] == 2000000

        funded = validate_success(
            api_client.transition_retainer_deposit(
                deposit["id"],
                transition_deposit_payload("FUND", 1999999),
                BILLING,
            ),
            200,
        )
        assert funded["status"] == "PARTIALLY_FUNDED"
        assert funded["received_cents"] == 1999999, (
            "one cent short of required"
        )

    def test_exact_required_amount_counts_as_funded(self):
        """PRD §2.7: "Retainer funding counts equality as funded: a held balance
        equal to the requirement is `FUNDED`."
        PRD §3.8: "The deposit's `status` is re-derived after every mutation:
        `PENDING` when nothing is held, `PARTIALLY_FUNDED` when the held balance
        is greater than zero but below the requirement, and `FUNDED` when the
        held balance is greater than or equal to the requirement — equality
        counts as funded."

        Design: Difficulty/boundary_precision_check/retainer_exact_equality_funded
        """
        _, _, matter, _, deposit = setup_matter_with_issued_letter(
            "Equality Client Inc"
        )
        assert deposit["required_cents"] == 2000000

        fund_deposit(deposit["id"], 1999999)
        topped_up = validate_success(
            api_client.transition_retainer_deposit(
                deposit["id"],
                transition_deposit_payload("FUND", 1),
                BILLING,
            ),
            200,
        )
        assert topped_up["received_cents"] == 2000000
        assert topped_up["status"] == "FUNDED", (
            "exact equality counts as funded: received >= required"
        )
