"""Coverage cap arithmetic and recommendation acceptance gates."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    setup_operation_with_active_plan,
    create_recommendation_payload,
)

ADVISOR = TEST_USERS["advisor_headers"]


class TestCoverageCap:
    def test_accept_at_cap_boundary_equality_allowed(self, api):
        """PRD §2.7: "for a plan, the cap is the floor of the plan's frozen
        expected-bushel snapshot multiplied by the smaller of the plan's own
        `max_priced_pct` ceiling and a risk-profile ceiling that is 0.60 for a
        `CONSERVATIVE` operation, 0.80 for a `BALANCED` operation, and 1.00 for
        an `AGGRESSIVE` operation. Acceptance of a hedge recommendation is
        permitted only when the plan's currently hedged bushels plus the
        recommendation's bushels plus the plan's already-priced contract
        bushels is less than or equal to the cap — equality is allowed, so a
        recommendation that lands exactly on the cap is accepted, and one that
        would exceed the cap by even one bushel is rejected with
        `ERR_COVERAGE_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/coverage_cap_nested_min_and_profile_branch
        """
        ctx = setup_operation_with_active_plan(
            name="Cap Farm", risk_profile="BALANCED", planted_acres=100,
            aph_yield_bushels=200, trend_yield_bushels=205, max_priced_pct=0.70,
        )
        plan = get_success_data(api.get_plan(ctx["plan"]["id"], ADVISOR))
        assert plan["coverage_cap_bushels"] == 14000, (
            f"plan max 0.70 must bind over the BALANCED profile cap 0.80: "
            f"floor(20000 * 0.70) == 14000, got {plan['coverage_cap_bushels']}"
        )
        rec_big = get_success_data(api.create_recommendation(
            create_recommendation_payload(plan["id"], bushels=14000), ADVISOR))
        accepted = api.accept_recommendation(rec_big["id"], make_grower_headers(ctx["operation"]["id"]))
        data = validate_success(accepted, expected_status=200)
        assert data["status"] == "ACCEPTED", "14000 <= 14000 — equality at the cap must be accepted"
        plan_after = get_success_data(api.get_plan(plan["id"], ADVISOR))
        assert plan_after["hedged_bushels"] == 14000, (
            f"accepted recommendation must count toward hedged_bushels, got {plan_after['hedged_bushels']}"
        )

    def test_accept_one_bushel_over_cap_rejected(self, api):
        """PRD §2.7: "Acceptance of a hedge recommendation is permitted only
        when the plan's currently hedged bushels plus the recommendation's
        bushels plus the plan's already-priced contract bushels is less than or
        equal to the cap — equality is allowed, so a recommendation that lands
        exactly on the cap is accepted, and one that would exceed the cap by
        even one bushel is rejected with `ERR_COVERAGE_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/coverage_cap_nested_min_and_profile_branch
        """
        ctx = setup_operation_with_active_plan(
            name="Cap Farm", risk_profile="BALANCED", planted_acres=100,
            aph_yield_bushels=200, trend_yield_bushels=205, max_priced_pct=0.70,
        )
        plan_id = ctx["plan"]["id"]
        rec_big = get_success_data(api.create_recommendation(
            create_recommendation_payload(plan_id, bushels=14000), ADVISOR))
        rec_one = get_success_data(api.create_recommendation(
            create_recommendation_payload(plan_id, bushels=1), ADVISOR))
        get_success_data(api.accept_recommendation(rec_big["id"], make_grower_headers(ctx["operation"]["id"])))
        resp = api.accept_recommendation(rec_one["id"], make_grower_headers(ctx["operation"]["id"]))
        validate_error(resp, ApiErrorId.ERR_COVERAGE_CAP_EXCEEDED)
        after = get_success_data(api.get_recommendation(rec_one["id"], ADVISOR))
        assert after["status"] == "PROPOSED", "a cap-rejected acceptance must leave the recommendation PROPOSED"
