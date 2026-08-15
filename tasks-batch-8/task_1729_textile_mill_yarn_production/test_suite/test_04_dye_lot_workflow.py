"""Dye lot submission gates, the rework loop, greige-yard conservation, vat cooldown."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    approve_recipe,
    assert_version_incremented,
    create_blend_recipe_payload,
    create_dye_lot,
    create_dye_lot_payload,
    create_fiber_lot,
    create_draft_recipe,
    create_lab_dip,
    create_shade_band,
    create_yarn_lot,
    get_success_data,
    record_quality_test,
    setup_approved_recipe,
    setup_dye_lot_in_dyeing,
    setup_dye_lot_shade_pending,
    setup_yarn_lot,
    start_dye_lot,
    submit_shade,
    reject_dye_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]
SUPERVISOR = TEST_USERS["spinning_supervisor_headers"]
OPERATOR = TEST_USERS["dye_house_operator_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
REP = TEST_USERS["customer_service_rep_headers"]


class TestRecipeQualityGate:
    def _setup_superseded_recipe_yarn_lot(self, api):
        """Yarn lot spun from a recipe that has since been SUPERSEDED."""
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(recipe_code="XDEP-A", target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 200.0)
        approve_recipe(recipe["id"])
        yarn_lot = create_yarn_lot(
            recipe["id"], spun_weight_lbs=180.0, actual_yarn_count_ne=20.0
        )
        # Revising the blend supersedes the approved recipe with the same code.
        replacement = get_success_data(
            api.create_blend_recipe(
                create_blend_recipe_payload(
                    recipe_code="XDEP-A", target_yarn_count_ne=24.0
                ),
                PLANNER,
            )
        )
        assert replacement["status"] == "DRAFT"
        shade_band = create_shade_band()
        return yarn_lot, shade_band, recipe

    def test_dye_create_superseded_recipe_quality_gate(self, api):
        """PRD §3.4: "And the recipe the yarn was spun from must still be `APPROVED` — dyeing yarn from a recipe that has left that state is a quality-gate violation, rejected with `ERR_QUALITY_GATE_FAILED`."
        PRD §3.1: "There is one deliberate exception — creating a fresh recipe whose `recipe_code` matches a currently `APPROVED` recipe is how the mill revises a blend: the incoming recipe is created in `DRAFT`, and the previously approved recipe with that code is automatically moved from `APPROVED` to `SUPERSEDED`."

        Design: Difficulty/cross_entity_state_dependency/dye_lot_create_requires_recipe_approved
        """
        yarn_lot, shade_band, old_recipe = \
            self._setup_superseded_recipe_yarn_lot(api)
        superseded = validate_success(api.get_blend_recipe(old_recipe["id"], PLANNER))
        assert superseded["status"] == "SUPERSEDED"

        resp = api.create_dye_lot(
            create_dye_lot_payload(
                yarn_lot["id"], shade_band["id"],
                vat_id="VAT-01", scheduled_at="2026-08-14T08:00:00Z",
                requested_yards=1000.0,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_QUALITY_GATE_FAILED)

    def test_failed_dye_create_leaves_yarn_lot_untouched(self, api):
        """PRD §3.4: "On success the dye lot is created in `SUBMITTED`, the yarn lot moves from `GREIGE` to `DYEING`, its `greige_yards_available` is debited by the requested yards, and the yarn lot's `version` increments as part of the cascade."
        PRD §3.4: "And the recipe the yarn was spun from must still be `APPROVED` — dyeing yarn from a recipe that has left that state is a quality-gate violation, rejected with `ERR_QUALITY_GATE_FAILED`."

        Design: Difficulty/cross_entity_state_dependency/dye_lot_create_requires_recipe_approved
        """
        yarn_lot, shade_band, _old = self._setup_superseded_recipe_yarn_lot(api)
        before = validate_success(api.get_yarn_lot(yarn_lot["id"], SUPERVISOR))

        resp = api.create_dye_lot(
            create_dye_lot_payload(
                yarn_lot["id"], shade_band["id"],
                vat_id="VAT-01", scheduled_at="2026-08-14T08:00:00Z",
                requested_yards=1000.0,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_QUALITY_GATE_FAILED)

        after = validate_success(api.get_yarn_lot(yarn_lot["id"], SUPERVISOR))
        assert after["status"] == "GREIGE"
        assert after["greige_yards_available"] == pytest.approx(
            before["greige_yards_available"]
        ), "A rejected submission must not debit greige yards"
        assert after["version"] == before["version"], (
            "A rejected submission must not advance the yarn lot version"
        )
        dye_lots, meta = validate_paginated(
            api.list_dye_lots(OPERATOR, params={"yarn_lot_id": yarn_lot["id"]})
        )
        assert meta["total_count"] == 0, "No dye lot may be persisted"


class TestGreigeCapacityBoundary:
    def test_dye_request_exactly_available_succeeds(self, api):
        """PRD §3.4: "Its `greige_yards_available` must cover the `requested_yards`, else `ERR_INSUFFICIENT_CAPACITY`."
        PRD §3.4: "On success the dye lot is created in `SUBMITTED`, the yarn lot moves from `GREIGE` to `DYEING`, its `greige_yards_available` is debited by the requested yards, and the yarn lot's `version` increments as part of the cascade."

        Design: Difficulty/boundary_precision_check/yarn_lot_zero_greige_yards_dye_submission
        """
        ctx = setup_yarn_lot(spun_weight_lbs=100.0)
        # 100 lbs at Ne 20 -> 100 * 16,800 = 1,680,000 greige yards available.
        dye_lot = create_dye_lot(
            ctx["yarn_lot"]["id"], ctx["shade_band"]["id"],
            requested_yards=1680000.0,
        )
        assert dye_lot["status"] == "SUBMITTED"
        yarn = validate_success(api.get_yarn_lot(ctx["yarn_lot"]["id"], SUPERVISOR))
        assert yarn["greige_yards_available"] == pytest.approx(0.0), (
            "Requesting exactly the available yardage drains the lot to zero"
        )
        assert yarn["status"] == "DYEING"

    def test_dye_request_above_available_rejected(self, api):
        """PRD §3.4: "Its `greige_yards_available` must cover the `requested_yards`, else `ERR_INSUFFICIENT_CAPACITY`."

        Design: Difficulty/boundary_precision_check/yarn_lot_zero_greige_yards_dye_submission
        """
        ctx = setup_yarn_lot(spun_weight_lbs=100.0)
        resp = api.create_dye_lot(
            create_dye_lot_payload(
                ctx["yarn_lot"]["id"], ctx["shade_band"]["id"],
                vat_id="VAT-01", scheduled_at="2026-08-14T08:00:00Z",
                requested_yards=1680000.01,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CAPACITY)
        yarn = validate_success(api.get_yarn_lot(ctx["yarn_lot"]["id"], SUPERVISOR))
        assert yarn["status"] == "GREIGE"
        assert yarn["greige_yards_available"] == pytest.approx(1680000.0)


class TestReworkLoop:
    def test_rework_loop_returns_lot_to_greige(self, api):
        """PRD §3.5: "Rejection from `SHADE_PENDING` moves the dye lot to `REJECTED` and runs the rework loop — the loop is, in the normal course, how a lot whose quality test graded `REJECTED` gives its yarn back: the yarn lot returns from `DYEING` to `GREIGE`, its `greige_yards_available` is credited back by the dye lot's `requested_yards`, its `version` increments, and the lot may be resubmitted in a fresh dye lot."

        Design: Difficulty/non_linear_state_machine/yarn_lot_rework_cycle_greige_dyeing_greige
        """
        ctx = setup_dye_lot_shade_pending(
            shrinkage_pct_provisional=9.0, hand_score=2, shrinkage_pct_final=None,
            requested_yards=5000.0,
        )
        rejected = reject_dye_lot(ctx["dye_lot"]["id"])
        assert rejected["status"] == "REJECTED"

        yarn = validate_success(api.get_yarn_lot(ctx["yarn_lot"]["id"], SUPERVISOR))
        assert yarn["status"] == "GREIGE", "The lot cycles DYEING -> GREIGE for rework"
        # 180 lbs at Ne 20 -> 3,024,000 initial; 5,000 debited then credited back.
        assert yarn["greige_yards_available"] == pytest.approx(3024000.0)

    def test_reworked_lot_resubmits(self, api):
        """PRD §3.5: "Rejection from `SHADE_PENDING` moves the dye lot to `REJECTED` and runs the rework loop — the loop is, in the normal course, how a lot whose quality test graded `REJECTED` gives its yarn back: the yarn lot returns from `DYEING` to `GREIGE`, its `greige_yards_available` is credited back by the dye lot's `requested_yards`, its `version` increments, and the lot may be resubmitted in a fresh dye lot."

        Design: Difficulty/non_linear_state_machine/yarn_lot_rework_cycle_greige_dyeing_greige
        """
        ctx = setup_dye_lot_shade_pending(
            shrinkage_pct_provisional=9.0, hand_score=2, shrinkage_pct_final=None,
            requested_yards=5000.0,
        )
        reject_dye_lot(ctx["dye_lot"]["id"])

        second = create_dye_lot(
            ctx["yarn_lot"]["id"], ctx["shade_band"]["id"],
            vat_id="VAT-02", scheduled_at="2026-08-15T08:00:00Z",
            requested_yards=5000.0,
        )
        assert second["status"] == "SUBMITTED", (
            "The reworked lot may be resubmitted in a fresh dye lot"
        )
        yarn = validate_success(api.get_yarn_lot(ctx["yarn_lot"]["id"], SUPERVISOR))
        assert yarn["status"] == "DYEING"
        assert yarn["greige_yards_available"] == pytest.approx(3019000.0)


class TestGreigeConservation:
    def test_greige_conservation_bookkeeping(self, api):
        """PRD §3.4: "On success the dye lot is created in `SUBMITTED`, the yarn lot moves from `GREIGE` to `DYEING`, its `greige_yards_available` is debited by the requested yards, and the yarn lot's `version` increments as part of the cascade."
        PRD §3.5: "the yarn lot returns from `DYEING` to `GREIGE`, its `greige_yards_available` is credited back by the dye lot's `requested_yards`, its `version` increments, and the lot may be resubmitted in a fresh dye lot."

        Design: Difficulty/compensating_invariant/greige_yards_conservation_dye_and_reject
        """
        ctx = setup_yarn_lot(spun_weight_lbs=180.0)
        yarn_id = ctx["yarn_lot"]["id"]
        initial = ctx["yarn_lot"]["greige_yards_available"]
        assert initial == pytest.approx(3024000.0)

        dye_lot = create_dye_lot(
            yarn_id, ctx["shade_band"]["id"], requested_yards=5000.0
        )
        mid = validate_success(api.get_yarn_lot(yarn_id, SUPERVISOR))
        assert mid["greige_yards_available"] == pytest.approx(3019000.0), (
            "3,024,000 - 5,000 committed to the dye lot"
        )

        start_dye_lot(dye_lot["id"])
        record_quality_test(dye_lot["id"], shrinkage_pct_provisional=9.0,
                            hand_score=2)
        submit_shade(dye_lot["id"])
        reject_dye_lot(dye_lot["id"])

        restored = validate_success(api.get_yarn_lot(yarn_id, SUPERVISOR))
        assert restored["greige_yards_available"] == pytest.approx(3024000.0), (
            "Reject credits the requested yards back, restoring the initial level"
        )
        assert restored["status"] == "GREIGE"

    def test_greige_conservation_version_increments(self, api):
        """PRD §2.6: "When an operation on one resource changes the facts another resource's state depends on, the system reconciles the dependent resource immediately — refreshing its `updated_at` and incrementing its `version` — without waiting for a separate client request."
        PRD §3.4: "On success the dye lot is created in `SUBMITTED`, the yarn lot moves from `GREIGE` to `DYEING`, its `greige_yards_available` is debited by the requested yards, and the yarn lot's `version` increments as part of the cascade."

        Design: Difficulty/compensating_invariant/greige_yards_conservation_dye_and_reject
        """
        ctx = setup_yarn_lot(spun_weight_lbs=180.0)
        yarn_id = ctx["yarn_lot"]["id"]
        v0 = ctx["yarn_lot"]["version"]

        dye_lot = create_dye_lot(
            yarn_id, ctx["shade_band"]["id"], requested_yards=5000.0
        )
        after_create = validate_success(api.get_yarn_lot(yarn_id, SUPERVISOR))
        assert_version_incremented(after_create["version"], v0)

        start_dye_lot(dye_lot["id"])
        record_quality_test(dye_lot["id"], shrinkage_pct_provisional=9.0,
                            hand_score=2)
        submit_shade(dye_lot["id"])
        reject_dye_lot(dye_lot["id"])

        after_reject = validate_success(api.get_yarn_lot(yarn_id, SUPERVISOR))
        assert_version_incremented(after_reject["version"], after_create["version"])
        assert after_reject["greige_yards_available"] == pytest.approx(3024000.0)


class TestVatCooldown:
    def _setup_two_yarn_lots(self, api):
        base = setup_approved_recipe(component_weight_lbs=400.0)
        yl_a = create_yarn_lot(base["recipe"]["id"], spun_weight_lbs=100.0,
                               actual_yarn_count_ne=20.0)
        yl_b = create_yarn_lot(base["recipe"]["id"], spun_weight_lbs=80.0,
                               actual_yarn_count_ne=20.0)
        shade_band = create_shade_band()
        return yl_a, yl_b, shade_band

    def test_vat_cooldown_conflict(self, api):
        """PRD §2.9: "Dye vats need turn-around time between batches: two dye lots sharing the same `vat_id` must respect a 30-minute cooldown between their scheduled batches, measured against each lot's `scheduled_at` instant. Either violation is rejected with `ERR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vat_buffer_cooldown_between_dye_lots
        """
        yl_a, yl_b, shade_band = self._setup_two_yarn_lots(api)
        create_dye_lot(yl_a["id"], shade_band["id"], vat_id="VAT-BUF",
                       scheduled_at="2026-08-14T08:00:00Z", requested_yards=1000.0)
        resp = api.create_dye_lot(
            create_dye_lot_payload(
                yl_b["id"], shade_band["id"], vat_id="VAT-BUF",
                scheduled_at="2026-08-14T08:15:00Z", requested_yards=1000.0,
            ),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_CONFLICT)

    def test_vat_cooldown_exactly_30_minutes_allowed(self, api):
        """PRD §2.9: "Dye vats need turn-around time between batches: two dye lots sharing the same `vat_id` must respect a 30-minute cooldown between their scheduled batches, measured against each lot's `scheduled_at` instant."
        PRD §3.4: "The vat and schedule fields are not decorative: they feed the §2.9 cooldown rule, which rejects a batch that would land on the same `vat_id` within half an hour of another batch with `ERR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/vat_buffer_cooldown_between_dye_lots
        """
        yl_a, yl_b, shade_band = self._setup_two_yarn_lots(api)
        create_dye_lot(yl_a["id"], shade_band["id"], vat_id="VAT-BUF",
                       scheduled_at="2026-08-14T08:00:00Z", requested_yards=1000.0)
        # Exactly 30 minutes later is not "within half an hour": the cooldown clears.
        second = create_dye_lot(yl_b["id"], shade_band["id"], vat_id="VAT-BUF",
                                scheduled_at="2026-08-14T08:30:00Z",
                                requested_yards=1000.0)
        assert second["status"] == "SUBMITTED"


class TestLabDipConversation:
    def test_lab_dip_double_approve_rejected(self, api):
        """PRD §3.3: "Approval requires the dip to be `PENDING` and its `measured_delta_e` to fall within the band's tolerance; a dip whose measured difference exceeds the tolerance cannot be approved and is rejected with `ERR_SHADE_OUT_OF_BAND`. Rejection from `PENDING` needs no further condition. Both outcomes are terminal."

        Design: Corner/state_machines/lab_dip_approve_idempotency_violation
        """
        band = create_shade_band(delta_e_tolerance=1.5)
        dip = create_lab_dip(band["id"], measured_delta_e=1.0)

        first = validate_success(api.approve_lab_dip(dip["id"], REP))
        assert first["status"] == "APPROVED"

        resp = api.approve_lab_dip(dip["id"], REP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_lab_dip_out_of_band_cannot_approve(self, api):
        """PRD §3.3: "Approval requires the dip to be `PENDING` and its `measured_delta_e` to fall within the band's tolerance; a dip whose measured difference exceeds the tolerance cannot be approved and is rejected with `ERR_SHADE_OUT_OF_BAND`."

        Design: Corner/validations/shade_out_of_band_lab_dip_approval
        """
        band = create_shade_band(delta_e_tolerance=1.5)
        dip = create_lab_dip(band["id"], measured_delta_e=2.0)
        resp = api.approve_lab_dip(dip["id"], REP)
        validate_error(resp, ApiErrorId.ERR_SHADE_OUT_OF_BAND)

        after = validate_success(api.get_lab_dip(dip["id"], REP))
        assert after["status"] == "PENDING", "A blocked approval leaves the dip PENDING"
