"""Location standing penalties and the cross-location brand risk index."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    assert_agreement_status_matches_level,
    assert_location,
    assert_risk_tier_matches_index,
    setup_two_finalized_visits,
    validate_paginated,
    validate_success,
)


class TestStandingPenaltyTier:
    def test_repeat_penalty_rate_is_keyed_off_the_pre_penalty_base(self):
        """The per-unit deduction is chosen from the base before it is deducted.

        PRD: "The repeat-violation penalty is then keyed off that **pre-penalty base**,
        never off the post-penalty result: the per-unit deduction is 0.50 when the base is
        at least 90.00, 1.00 when the base is at least 80.00, and 2.00 otherwise."

        Design: Difficulty/combinatorial_formula/standing_penalty_tier_keyed_off_pre_penalty_base
        """
        program = setup_two_finalized_visits()

        assert program["first_visit"]["composite_score"] == pytest.approx(90.66, abs=0.01)
        assert program["second_visit"]["composite_score"] == pytest.approx(90.66, abs=0.01)

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert_location(location)
        assert location["repeat_violation_count"] == 2, \
            "both critical food-safety items repeat across the two finalized visits"
        assert location["standing_score"] == pytest.approx(89.66, abs=0.01), \
            "a base of 90.66 selects the 0.50 rate, so 90.66 - 2 * 0.50 is 89.66"
        assert location["standing_score"] != pytest.approx(88.66, abs=0.01), \
            "keying the rate off the post-penalty 89.66 would wrongly deduct 1.00 per unit"
        assert location["latest_grade"] == "FAIL", \
            "the most recent visit carries two critical violations"

    def test_pre_penalty_base_is_the_renormalized_weighted_mean(self):
        """Two finalized visits renormalize the recency weights to five and three eighths.

        PRD: "Otherwise the recency weights one half, three tenths, and one fifth are
        truncated to the number of visits actually available and then renormalized by
        dividing each by the sum of the truncated weights — so a location with only two
        finalized visits weights them five eighths and three eighths."

        Design: Difficulty/combinatorial_formula/standing_penalty_tier_keyed_off_pre_penalty_base
        """
        program = setup_two_finalized_visits()

        first = program["first_visit"]["composite_score"]
        second = program["second_visit"]["composite_score"]
        pre_penalty_base = round(0.625 * second + 0.375 * first, 2)
        assert pre_penalty_base == pytest.approx(90.66, abs=0.01)

        location = validate_success(
            api_client.get_location(program["location"]["id"], ADMIN_HEADERS)
        )
        assert location["standing_score"] == pytest.approx(
            round(pre_penalty_base - 0.50 * location["repeat_violation_count"], 2), abs=0.01
        )
        assert location["escalation_level"] == 2, \
            "one REPEAT_CRITICAL entry per repeating rubric item"
        assert location["franchise_agreement_status"] == "CURE_PERIOD"
        assert_agreement_status_matches_level(location)

        open_actions, meta = validate_paginated(
            api_client.list_corrective_actions(
                ADMIN_HEADERS, params={"location_id": program["location"]["id"]}
            )
        )
        assert meta["total_count"] == 4, "each visit raised one action per violating item"
        assert location["open_corrective_action_count"] == 4
        assert all(action["severity"] == "CRITICAL" for action in open_actions)


class TestBrandRiskIndex:
    def test_risk_index_sums_the_deficit_the_caps_and_the_surcharge(self):
        """Four contributions, each with its own ceiling, make up the index.

        PRD: "The open-critical contribution is 6.00 for each corrective action of the
        brand whose `severity` is `CRITICAL` and whose `status` is one of `ASSIGNED`,
        `SUBMITTED`, `REJECTED`, `OVERDUE`, or `ESCALATED`, capped at 40.00 in total."

        Design: Difficulty/combinatorial_formula/brand_risk_index_nested_caps_and_conditional_surcharge
        """
        program = setup_two_finalized_visits()

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        assert risk["brand_id"] == program["brand"]["id"]
        assert risk["average_standing_score"] == pytest.approx(89.66, abs=0.01)
        assert risk["rated_location_count"] == 1
        assert risk["open_critical_action_count"] == 4
        assert risk["default_location_count"] == 1
        assert risk["fail_grade_surcharge_applied"] is True, \
            "the only rated location's latest_grade is FAIL"
        assert risk["brand_risk_index"] == pytest.approx(55.20, abs=0.01), \
            "0.60 * 10.34 + 24.00 + 10.00 + 15.00 rounds to 55.20"
        assert risk["brand_risk_tier"] == "ELEVATED"
        assert_risk_tier_matches_index(risk)

    def test_the_brand_read_reports_the_same_persisted_index(self):
        """The computed read persists its result, so the plain brand read agrees.

        PRD: "The cross-location risk figure is recomputed on visit finalize, visit void,
        dispute amendment, corrective-action verify, corrective-action escalation, and
        cure acceptance — and also whenever the computed risk read is taken, which
        recomputes the index and persists the fresh result on the brand before returning
        it."

        Design: Difficulty/combinatorial_formula/brand_risk_index_nested_caps_and_conditional_surcharge
        """
        program = setup_two_finalized_visits()

        risk = validate_success(
            api_client.get_brand_risk_index(program["brand"]["id"], ADMIN_HEADERS)
        )
        brand = validate_success(api_client.get_brand(program["brand"]["id"], ADMIN_HEADERS))

        assert brand["brand_risk_index"] == pytest.approx(55.20, abs=0.01)
        assert brand["brand_risk_index"] == pytest.approx(risk["brand_risk_index"], abs=0.01)
        assert brand["brand_risk_tier"] == "ELEVATED"
        assert brand["default_location_count"] == 1
        assert brand["location_count"] == 1, \
            "location_count moves only when a location is registered"
        assert_risk_tier_matches_index(brand)
