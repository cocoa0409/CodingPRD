"""Immediate consistency: the funding vote's own body already holds every derivation."""

from test_helpers import (
    CC_CERTIFIER,
    FC,
    assert_pct,
    assert_ratio,
    build_certified_scenario,
    make_committee_headers,
    validate_success,
)


class TestFundingIsVisibleImmediately:
    def test_the_vote_returns_the_whole_derivation_and_the_reread_agrees(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field." And PRD §3.4:
        "**Funding the pool** is the committee act that mints the money and moves the plan
        from `CERTIFIED` to `ALLOCATION_OPEN`." And PRD §3.4: "Processing the pools of the
        plan in ascending `created_at` order (an audit ordering that affects no figure), each
        pool's `funded_cents` becomes its `eligible_target_cents` multiplied by the plan's
        `funding_multiplier`, rounded half up to whole cents; its `min_utilization_cents`
        becomes 99.50 percent of `funded_cents` truncated downward to a whole cent — that is,
        `funded_cents` multiplied by 9950, divided by 10000, with any fraction discarded; and
        its `available_cents` becomes `funded_cents` minus `allocated_cents`." And PRD §3.4:
        "The plan's `funded_pool_cents` is the sum of the per-pool figures just written, and
        `aggregate_rounding_delta_cents` records the divergence described in §2.6."

        Design: Corner/consistency_model/funding_derivations_are_visible_in_the_same_response
        """
        scenario = build_certified_scenario(
            units=("L7",),
            plan_overrides={"plan_name": "FY26 Immediate Visibility Plan"},
        )
        assert scenario.refresh_pool("L7")["calibration_status"] == "SCORECARD_CERTIFIED"

        voted = validate_success(
            api.fund_pool(scenario.plan_id, make_committee_headers(CC_CERTIFIER))
        )
        assert voted["status"] == "ALLOCATION_OPEN"
        assert_pct(voted["blended_achievement_pct"], 100.00)
        assert_ratio(voted["funding_multiplier"], 1.0000)
        assert voted["total_target_cents"] == 4000000
        assert voted["funded_pool_cents"] == 4000000
        assert voted["discretionary_budget_cents"] == 400000
        assert voted["aggregate_rounding_delta_cents"] == 0

        # The re-read is the control: nothing in the vote's body was ahead of storage.
        stored = validate_success(api.get_bonus_plan(scenario.plan_id, FC))
        assert stored["status"] == voted["status"]
        assert stored["blended_achievement_pct"] == voted["blended_achievement_pct"]
        assert stored["funding_multiplier"] == voted["funding_multiplier"]
        assert stored["total_target_cents"] == voted["total_target_cents"]
        assert stored["funded_pool_cents"] == voted["funded_pool_cents"]
        assert (
            stored["discretionary_budget_cents"] == voted["discretionary_budget_cents"]
        )
        assert (
            stored["aggregate_rounding_delta_cents"]
            == voted["aggregate_rounding_delta_cents"]
        )

        pool = validate_success(api.get_bu_pool(scenario.pool_id("L7"), FC))
        assert pool["calibration_status"] == "FUNDED"
        assert pool["funded_cents"] == 4000000
        assert pool["min_utilization_cents"] == 3980000
        assert pool["available_cents"] == 4000000
        assert pool["allocated_cents"] == 0
        assert pool["eligible_target_cents"] == 4000000
        assert pool["eligible_headcount"] == 1
        assert pool["max_top_tier_count"] == 1
