"""Difficulty Rule 2 — combinatorial_formula.

(A) Per-tier-rounding-then-sum order for the title insurance premium at a
    price that straddles all four tiers ($1,200,000 → premium 440000 cents).
(B) The clear-to-close transition is the conjunction of six independent
    predicates across five entities — all six must hold; the formula is a
    non-linear AND over heterogeneous state attributes.
"""
from test_helpers import (
    validate_success,
    setup_actors,
    setup_active_agreement,
    setup_resolved_clean_title,
    issue_title_policy,
    setup_ready_for_clear_to_close,
)


class TestTitlePremiumPerTierRoundingStraddleFourTiers:
    """At purchase_price_cents=120000000 ($1.2M), every tier contributes:
    tier1: 100000 * 0.00450 = 450$  = 45000 cents
    tier2: 400000 * 0.00400 = 1600$ = 160000 cents
    tier3: 500000 * 0.00350 = 1750$ = 175000 cents
    tier4: 200000 * 0.00300 = 600$  = 60000 cents
    sum = 440000 cents.
    """

    def test_premium_at_1_2m_sums_four_per_tier_slices_to_440000(self, api):
        """PRD §3.2: "The price is sliced at three break-points — 100,000 dollars, 500,000 dollars, and 1,000,000 dollars — yielding four tiers with successively lower per-dollar rates: 0.00450 per dollar for the first 100,000 dollars (the cents-equivalent break is 10,000,000 cents), 0.00400 per dollar for the portion from 100,000 dollars up to 500,000 dollars (cents break at 50,000,000), 0.00350 per dollar for the portion from 500,000 dollars up to 1,000,000 dollars (cents break at 100,000,000), and 0.00300 per dollar for any portion above 1,000,000 dollars."
        PRD §3.2: "The amount that falls inside each tier is multiplied by that tier's per-dollar rate (after converting the slice from cents to dollars by dividing by 100), the resulting per-tier cent value is rounded half up to a whole cent, and the four rounded slices are then summed to produce the final ``premium_cents``."

        Design: Difficulty/combinatorial_formula/title_premium_per_tier_rounding_order_mode_b
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors,
            purchase_price_cents=120_000_000,
            earnest_money_required_cents=1_000_000,
            scheduled_closing_date="2026-08-01T00:00:00Z",
        )
        search = setup_resolved_clean_title(actors, base["agreement"]["id"])
        policy = issue_title_policy(actors, search["search_id"], search["version"])
        assert policy["premium_cents"] == 440000, \
            f"$1.2M four-tier sum: 45000+160000+175000+60000 = 440000, got {policy['premium_cents']}"
        assert policy["coverage_amount_cents"] == 120_000_000

    def test_premium_at_1_2m_yields_status_issued(self, api):
        """PRD §3.2: "Issuance creates the policy in ``ISSUED`` with ``version`` 1, sets ``coverage_amount_cents`` equal to the linked agreement's ``purchase_price_cents`` at the instant of issuance, and computes ``premium_cents`` per the marginal-tier formula below."

        Design: Difficulty/combinatorial_formula/title_premium_per_tier_rounding_order_mode_b
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors,
            purchase_price_cents=120_000_000,
            earnest_money_required_cents=1_000_000,
        )
        search = setup_resolved_clean_title(actors, base["agreement"]["id"])
        policy = issue_title_policy(actors, search["search_id"], search["version"])
        assert policy["status"] == "ISSUED"
        assert policy["version"] == 1


class TestClearToCloseSixInputPredicateConjunction:
    """Clear-to-close is the AND of six predicates: title RESOLVED+clean,
    policy ISSUED, CCR buyer_acknowledged, CD ACKNOWLEDGED, clock past
    earliest_consummation_at, all wires LOCKED. All six must hold.
    """

    def test_clear_to_close_succeeds_when_all_six_predicates_hold(self, api):
        """PRD §3.5: "Advancing the agreement from ``UNDER_CONTRACT`` to ``CLEARED_TO_CLOSE`` requires all of the following preconditions to hold concurrently: exactly one ``TitleSearch`` exists for the agreement with status ``RESOLVED`` and ``has_material_defect`` of ``false``; exactly one ``TitleInsurancePolicy`` exists in status ``ISSUED`` whose underlying search traces back to the agreement; exactly one ``CCRReview`` exists for the agreement with ``buyer_acknowledged`` of ``true``; exactly one ``ClosingDisclosure`` exists in status ``ACKNOWLEDGED``; the current UTC clock is at or after that disclosure's ``earliest_consummation_at``; and every ``WireInstruction`` belonging to the agreement is in status ``LOCKED``."

        Design: Difficulty/combinatorial_formula/clear_to_close_six_input_predicate_mode_a
        """
        ready = setup_ready_for_clear_to_close()
        res = api.clear_to_close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["co"]
        )
        agr = validate_success(res, expected_status=200)
        assert agr["status"] == "CLEARED_TO_CLOSE", \
            f"all six predicates hold → status must be CLEARED_TO_CLOSE, got {agr['status']}"

    def test_clear_to_close_version_increments_on_success(self, api):
        """PRD §3.5: "Advancing the agreement from ``UNDER_CONTRACT`` to ``CLEARED_TO_CLOSE`` requires all of the following preconditions to hold concurrently: exactly one ``TitleSearch`` exists for the agreement with status ``RESOLVED`` and ``has_material_defect`` of ``false``; exactly one ``TitleInsurancePolicy`` exists in status ``ISSUED`` whose underlying search traces back to the agreement; exactly one ``CCRReview`` exists for the agreement with ``buyer_acknowledged`` of ``true``; exactly one ``ClosingDisclosure`` exists in status ``ACKNOWLEDGED``; the current UTC clock is at or after that disclosure's ``earliest_consummation_at``; and every ``WireInstruction`` belonging to the agreement is in status ``LOCKED``."
        PRD §2.4: "The ``version`` field is an integer that begins at 1 and increments by exactly 1 every time the row mutates"

        Design: Difficulty/combinatorial_formula/clear_to_close_six_input_predicate_mode_a
        """
        ready = setup_ready_for_clear_to_close()
        before = validate_success(
            api.get_purchase_agreement(ready["agreement_id"], ready["actors"]["eo"]),
            expected_status=200,
        )
        version_before = before["version"]
        res = api.clear_to_close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["co"]
        )
        agr = validate_success(res, expected_status=200)
        assert agr["version"] == version_before + 1, \
            f"clear-to-close must bump version by 1, before={version_before} after={agr['version']}"
        assert agr["status"] == "CLEARED_TO_CLOSE"
