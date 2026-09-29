"""Recipe review lifecycle and the regrind cap comparison at its boundary."""
import pytest

from test_helpers import (
    ENGINEER,
    ApiErrorId,
    build_food_recipe_draft,
    build_non_food_recipe_draft,
    get_success_data,
    make_blend_engineer_headers,
    make_quality_manager_headers,
    setup_food_contact_catalog,
    setup_non_food_catalog,
    validate_error,
    validate_success,
)

REJECTION_REASON = "slip additive package not qualified for this customer"

R_FD_11_COMPONENTS = (
    (1, "VIRGIN", 30.0, "g_ll"),
    (2, "VIRGIN", 2.5, "g_ev"),
    (2, "VIRGIN", 7.5, "g_ti"),
    (3, "VIRGIN", 40.0, "g_ll"),
    (3, "ADDITIVE", 10.0, "g_ad"),
    (3, "REGRIND", 10.0, None),
)

R_FD_10_COMPONENTS = (
    (1, "VIRGIN", 25.0, "g_ll"),
    (2, "VIRGIN", 2.5, "g_ev"),
    (2, "VIRGIN", 7.5, "g_ti"),
    (3, "VIRGIN", 40.0, "g_ll"),
    (3, "ADDITIVE", 10.0, "g_ad"),
    (3, "REGRIND", 15.0, None),
)


def _submitted_non_food_recipe(api):
    """R-NF-0 at 100.0 pct LLDPE, submitted by u-be-1."""
    world = setup_non_food_catalog(api)
    recipe = build_non_food_recipe_draft(api, world, recipe_code="R-NF-0")
    world["recipe"] = validate_success(
        api.submit_blend_recipe(recipe["id"], make_blend_engineer_headers("u-be-1")),
        200)
    return world


class TestRejectReopenResubmitCycle:
    """REJECTED is not terminal: the recipe can re-enter DRAFT and go round again."""

    def test_rejection_stores_the_reason_and_reopen_clears_the_review_stamps(self, api):
        """Reopening wipes both review fields but keeps the components.

        PRD: "Reopening clears both `submitted_by_user_id` and
        `rejection_reason`; the existing `components` survive and may be
        extended by further appends."

        Design: Difficulty/non_linear_state_machine/recipe_reject_reopen_resubmit_cycle_reenters_draft
        """
        world = _submitted_non_food_recipe(api)
        recipe_id = world["recipe"]["id"]

        rejected = validate_success(
            api.reject_blend_recipe(recipe_id, REJECTION_REASON,
                                    make_quality_manager_headers("u-qm-1")), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == REJECTION_REASON

        reopened = validate_success(
            api.reopen_blend_recipe(recipe_id, make_blend_engineer_headers("u-be-1")),
            200)
        assert reopened["status"] == "DRAFT"
        assert reopened["rejection_reason"] is None
        assert reopened["submitted_by_user_id"] is None
        assert reopened["total_weight_pct"] == pytest.approx(100.000, abs=0.01)
        assert len(reopened["components"]) == 1

    def test_second_pass_restamps_the_submitter_and_recomputes_the_blend(self, api):
        """A different engineer may submit the reopened draft.

        PRD: "The full cycle `DRAFT → SUBMITTED → REJECTED → DRAFT →
        SUBMITTED` is therefore legitimate and each pass re-runs every blend
        calculation against the extended component list."

        Design: Difficulty/non_linear_state_machine/recipe_reject_reopen_resubmit_cycle_reenters_draft
        """
        world = _submitted_non_food_recipe(api)
        recipe_id = world["recipe"]["id"]
        get_success_data(api.reject_blend_recipe(
            recipe_id, REJECTION_REASON, make_quality_manager_headers("u-qm-1")))
        get_success_data(api.reopen_blend_recipe(
            recipe_id, make_blend_engineer_headers("u-be-1")))

        resubmitted = validate_success(
            api.submit_blend_recipe(recipe_id,
                                    make_blend_engineer_headers("u-be-2")), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submitted_by_user_id"] == "u-be-2"
        assert resubmitted["strength_index"] == pytest.approx(42.00, abs=0.01)
        assert resubmitted["blend_cost_per_kg"] == pytest.approx(1.45, abs=0.01)

    def test_the_reopened_recipe_can_still_reach_approved(self, api):
        """Approval freezes food-contact eligibility on the second pass too.

        PRD: "Approval moves `SUBMITTED → APPROVED`, requires that the acting
        `X-User-ID` differ from `submitted_by_user_id`", and it "stamps
        `approved_by_user_id` and freezes `food_contact_eligible`."

        Design: Difficulty/non_linear_state_machine/recipe_reject_reopen_resubmit_cycle_reenters_draft
        """
        world = _submitted_non_food_recipe(api)
        recipe_id = world["recipe"]["id"]
        get_success_data(api.reject_blend_recipe(
            recipe_id, REJECTION_REASON, make_quality_manager_headers("u-qm-1")))
        get_success_data(api.reopen_blend_recipe(
            recipe_id, make_blend_engineer_headers("u-be-1")))
        get_success_data(api.submit_blend_recipe(
            recipe_id, make_blend_engineer_headers("u-be-2")))

        approved = validate_success(
            api.approve_blend_recipe(recipe_id,
                                     make_quality_manager_headers("u-qm-1")), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-qm-1"
        assert approved["food_contact_eligible"] is True


class TestRegrindCapComparisonBoundary:
    """Equality at the cap passes; half a point above it does not."""

    @staticmethod
    def _two_drafts(api):
        world = setup_food_contact_catalog(api)
        world["r11"] = build_food_recipe_draft(api, world, recipe_code="R-FD-11",
                                               components=R_FD_11_COMPONENTS)
        world["r10"] = build_food_recipe_draft(api, world, recipe_code="R-FD-10",
                                               components=R_FD_10_COMPONENTS)
        return world

    def test_regrind_exactly_at_the_cap_is_accepted(self, api):
        """10.000 regrind against a 10.000 cap submits cleanly.

        PRD: "Step four compares: the cap is satisfied when `regrind_pct` is
        less than or equal to `regrind_cap_pct`, with equality at the cap
        accepted."

        Design: Difficulty/boundary_precision_check/regrind_pct_exactly_at_cap_versus_one_half_point_above
        """
        world = self._two_drafts(api)
        submitted = validate_success(
            api.submit_blend_recipe(world["r11"]["id"],
                                    make_blend_engineer_headers("u-be-1")), 200)

        assert submitted["status"] == "SUBMITTED"
        assert submitted["regrind_pct"] == pytest.approx(10.000, abs=0.01)
        assert submitted["regrind_cap_pct"] == pytest.approx(10.000, abs=0.01)
        assert submitted["pcr_band"] == "LOW"

    def test_accepted_blend_reports_its_derived_figures(self, api):
        """The accepted at-cap blend publishes cost, density and nominal content.

        PRD: "Step five computes `nominal_recycled_content_pct` as
        `virgin_pcr_pct` plus `regrind_pct` divided by one hundred multiplied by
        the product's `assumed_regrind_pcr_pct`, rounded to three decimals".

        Design: Difficulty/boundary_precision_check/regrind_pct_exactly_at_cap_versus_one_half_point_above
        """
        world = self._two_drafts(api)
        submitted = validate_success(
            api.submit_blend_recipe(world["r11"]["id"],
                                    make_blend_engineer_headers("u-be-1")), 200)

        assert submitted["strength_index"] == pytest.approx(34.61, abs=0.01)
        assert submitted["blend_cost_per_kg"] == pytest.approx(1.96, abs=0.01)
        assert submitted["blended_density_kg_m3"] == pytest.approx(927.80, abs=0.01)
        assert submitted["nominal_recycled_content_pct"] == pytest.approx(0.500,
                                                                         abs=0.01)
        assert submitted["barrier_layer_present"] is True

    def test_regrind_half_a_point_above_the_cap_is_refused(self, api):
        """15.000 regrind against the same 10.000 cap is refused.

        PRD: "`regrind_pct` must be no greater than `regrind_cap_pct`, or
        `ERR_REGRIND_CAP_EXCEEDED` — equality at the cap passes."

        Design: Difficulty/boundary_precision_check/regrind_pct_exactly_at_cap_versus_one_half_point_above
        """
        world = self._two_drafts(api)
        validate_error(
            api.submit_blend_recipe(world["r10"]["id"],
                                    make_blend_engineer_headers("u-be-1")),
            ApiErrorId.ERR_REGRIND_CAP_EXCEEDED, 422)

        refused = get_success_data(api.get_blend_recipe(world["r10"]["id"], ENGINEER))
        assert refused["status"] == "DRAFT"
        assert refused["regrind_pct"] == pytest.approx(15.000, abs=0.01)
        assert refused["regrind_cap_pct"] == pytest.approx(10.000, abs=0.01)
        assert refused["nominal_recycled_content_pct"] == pytest.approx(0.750, abs=0.01)
