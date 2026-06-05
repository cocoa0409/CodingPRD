"""Corner section: calculations — title insurance premium at the lower
tier boundary, and the input-set filter that only RESOLVED clean searches
may be insured.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_actors,
    setup_active_agreement,
    setup_resolved_clean_title,
    issue_title_policy,
    create_title_search,
    complete_title_search,
    create_title_insurance_policy_payload,
    api_client,
)


class TestTitlePremiumAtLowerTierBoundary:
    def test_premium_at_250k_is_105000_per_two_tier_slice(self, api):
        """PRD §3.2: "The price is sliced at three break-points — 100,000 dollars, 500,000 dollars, and 1,000,000 dollars — yielding four tiers with successively lower per-dollar rates: 0.00450 per dollar for the first 100,000 dollars (the cents-equivalent break is 10,000,000 cents), 0.00400 per dollar for the portion from 100,000 dollars up to 500,000 dollars (cents break at 50,000,000), 0.00350 per dollar for the portion from 500,000 dollars up to 1,000,000 dollars (cents break at 100,000,000), and 0.00300 per dollar for any portion above 1,000,000 dollars."
        PRD §3.2: "The amount that falls inside each tier is multiplied by that tier's per-dollar rate (after converting the slice from cents to dollars by dividing by 100), the resulting per-tier cent value is rounded half up to a whole cent, and the four rounded slices are then summed to produce the final ``premium_cents``."

        Design: Corner/calculations/title_premium_at_lower_tier_boundary_250k
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors,
            purchase_price_cents=25_000_000,  # $250K
            earnest_money_required_cents=1_000_000,
        )
        search = setup_resolved_clean_title(actors, base["agreement"]["id"])
        policy = issue_title_policy(actors, search["search_id"], search["version"])
        # tier1: 100000 * 0.00450 = 450$ → 45000 cents
        # tier2: 150000 * 0.00400 = 600$ → 60000 cents
        # Sum = 105000.
        assert policy["premium_cents"] == 105000, \
            f"$250K straddles tier1+tier2: 45000+60000 = 105000, got {policy['premium_cents']}"


class TestTitlePolicyInsurabilityFilter:
    def test_issue_policy_on_completed_not_resolved_search_returns_title_not_insurable(self, api):
        """PRD §3.2: "The referenced search must be in status ``RESOLVED`` with ``has_material_defect`` of ``false``; otherwise the issuance is rejected with ``ERR_TITLE_NOT_INSURABLE``."

        Design: Corner/calculations/title_premium_input_set_only_RESOLVED_clean_search
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        search = create_title_search(actors, base["agreement"]["id"])
        completed = complete_title_search(actors, search["id"], defects=[])
        # Search is COMPLETED (not RESOLVED) with has_material_defect=false.
        res = api.create_title_insurance_policy(
            create_title_insurance_policy_payload(
                title_search_id=search["id"],
                expected_title_search_version=completed["version"],
            ),
            actors["ta"],
        )
        validate_error(res, "ERR_TITLE_NOT_INSURABLE", expected_status=409)
