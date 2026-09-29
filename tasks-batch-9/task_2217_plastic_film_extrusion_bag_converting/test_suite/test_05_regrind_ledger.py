"""The regrind ledger: compensating reversals and the two recycled-content variants."""
import pytest

from test_helpers import (
    ADMIN,
    CLOCK_D1_1500,
    ENGINEER,
    EXTRUDER,
    ApiErrorId,
    ISSUING_MANAGER,
    add_gauge_readings,
    assert_pool_mass_invariants,
    assert_regrind_transaction,
    create_extrusion_run_payload,
    get_success_data,
    pcr_grade_payload,
    read_pool_version,
    set_logical_clock,
    setup_approved_non_food_recipe,
    setup_non_food_catalog,
    setup_pool_with_reincorporation,
    validate_error,
    validate_paginated,
    validate_success,
)

R_NF_6_COMPONENTS = ((1, "VIRGIN", 50.0, "g_ll"), (1, "VIRGIN", 50.0, "g_pc"))
R_NF_3_COMPONENTS = ((1, "VIRGIN", 50.0, "g_ll"), (1, "VIRGIN", 18.0, "g_pc"),
                     (1, "REGRIND", 32.0, None))


class TestRegrindReversalRestoresPoolMass:
    """A reversal is a compensating append, never a mutation of the target row."""

    def test_outbound_row_records_the_draw_before_it_is_reversed(self, api):
        """The draw books an OUT reincorporation row with a balance snapshot.

        PRD: "The draw books a row with `direction` `OUT` and `origin_kind`
        `REINCORPORATION`, whose `pcr_kg` is the drawn `kg` multiplied by the
        pool's `embedded_pcr_pct`".

        Design: Difficulty/compensating_invariant/regrind_reversal_restores_pool_mass_invariant
        """
        world = setup_pool_with_reincorporation(api)
        txn = get_success_data(
            api.get_regrind_transaction(world["out_transaction"]["id"], EXTRUDER))

        assert_regrind_transaction(txn)
        assert txn["direction"] == "OUT"
        assert txn["origin_kind"] == "REINCORPORATION"
        assert txn["kg"] == pytest.approx(50.000, abs=0.01)
        assert txn["pcr_kg"] == pytest.approx(0.000, abs=0.01)
        assert txn["pool_available_kg_after"] == pytest.approx(50.000, abs=0.01)

    def test_reversal_returns_the_pool_to_its_pre_draw_balances(self, api):
        """Removing the target from the input set restores every aggregate.

        PRD: "A reversal row is itself never summed — its only effect is to
        remove its target from the input set."

        Design: Difficulty/compensating_invariant/regrind_reversal_restores_pool_mass_invariant
        """
        world = setup_pool_with_reincorporation(api)
        validate_success(api.reverse_regrind_transaction(
            world["out_transaction"]["id"], "wrong pool drawn at the blender",
            ISSUING_MANAGER), 201)

        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["available_kg"] == pytest.approx(100.000, abs=0.01)
        assert pool["cumulative_in_kg"] == pytest.approx(100.000, abs=0.01)
        assert pool["cumulative_out_kg"] == pytest.approx(0.000, abs=0.01)
        assert pool["cumulative_in_pcr_kg"] == pytest.approx(0.000, abs=0.01)
        assert pool["embedded_pcr_pct"] == pytest.approx(0.000, abs=0.01)
        assert pool["generation_count"] == 1
        assert pool["reincorporation_count"] == 0
        assert_pool_mass_invariants(pool)

    def test_reversal_row_is_appended_with_the_opposite_direction(self, api):
        """The compensation is recorded as its own inbound row.

        PRD: "Reversing a target row books a new row whose `origin_kind` is
        `REVERSAL`, whose `reverses_transaction_id` names the target, whose `kg`
        equals the target's `kg`, and whose `direction` is opposite".

        Design: Difficulty/compensating_invariant/regrind_reversal_restores_pool_mass_invariant
        """
        world = setup_pool_with_reincorporation(api)
        get_success_data(api.reverse_regrind_transaction(
            world["out_transaction"]["id"], "wrong pool drawn at the blender",
            ISSUING_MANAGER))

        rows, meta = validate_paginated(api.list_regrind_transactions(
            EXTRUDER,
            params={"reverses_transaction_id": world["out_transaction"]["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["direction"] == "IN"
        assert rows[0]["origin_kind"] == "REVERSAL"

    def test_second_reversal_of_the_same_row_is_refused(self, api):
        """Because the compensation is recorded, it cannot be applied twice.

        PRD: "a target already referenced by an existing reversal yields
        `ERR_TRANSACTION_ALREADY_REVERSED`".

        Design: Difficulty/compensating_invariant/regrind_reversal_restores_pool_mass_invariant
        """
        world = setup_pool_with_reincorporation(api)
        get_success_data(api.reverse_regrind_transaction(
            world["out_transaction"]["id"], "wrong pool drawn at the blender",
            ISSUING_MANAGER))

        validate_error(api.reverse_regrind_transaction(
            world["out_transaction"]["id"], "duplicate correction attempt",
            ISSUING_MANAGER), ApiErrorId.ERR_TRANSACTION_ALREADY_REVERSED, 409)

        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["available_kg"] == pytest.approx(100.000, abs=0.01)

    def test_reversal_decrements_the_consuming_run(self, api):
        """The run that drew the mass gives it back and keeps running.

        PRD: "When the reversed target was a reincorporation, the consuming run's
        `regrind_consumed_kg` is decremented and its `regrind_actual_pct`
        re-derived."

        Design: Difficulty/compensating_invariant/regrind_reversal_restores_pool_mass_invariant
        """
        world = setup_pool_with_reincorporation(api)
        get_success_data(api.reverse_regrind_transaction(
            world["out_transaction"]["id"], "wrong pool drawn at the blender",
            ISSUING_MANAGER))

        run2 = get_success_data(api.get_extrusion_run(world["run2"]["id"], EXTRUDER))
        assert run2["regrind_consumed_kg"] == pytest.approx(0.000, abs=0.01)
        assert run2["status"] == "RUNNING"


class TestNominalVersusAsBuiltRecycledContent:
    """The recipe's nominal figure and the run's as-built figure diverge."""

    @staticmethod
    def _two_runs(api):
        world = setup_non_food_catalog(api)
        world["g_pc"] = get_success_data(
            api.create_resin_grade(pcr_grade_payload(), ADMIN))

        world = setup_approved_non_food_recipe(api=api, world=world,
                                               recipe_code="R-NF-6",
                                               components=R_NF_6_COMPONENTS)
        world["r6"] = world["recipe"]
        run_y = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["r6"]["id"],
                                         run_code="RUN-NF-Y",
                                         scheduled_start="2026-08-05T06:00:00Z",
                                         scheduled_end="2026-08-05T14:00:00Z",
                                         target_output_kg=500.0),
            EXTRUDER))
        get_success_data(api.start_extrusion_run(run_y["id"], EXTRUDER))
        add_gauge_readings(api, run_y["id"], (40.0,) * 5)
        world["run_y"] = get_success_data(
            api.complete_extrusion_run(run_y["id"], 500.0, 100.0, EXTRUDER))

        world = setup_approved_non_food_recipe(api=api, world=world,
                                               recipe_code="R-NF-3",
                                               components=R_NF_3_COMPONENTS)
        world["r3"] = world["recipe"]
        set_logical_clock(api, CLOCK_D1_1500)
        run_z = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["r3"]["id"],
                                         run_code="RUN-NF-Z",
                                         scheduled_start="2026-08-05T15:00:00Z",
                                         scheduled_end="2026-08-05T20:00:00Z",
                                         target_output_kg=1000.0),
            EXTRUDER))
        get_success_data(api.start_extrusion_run(run_z["id"], EXTRUDER))
        add_gauge_readings(api, run_z["id"], (40.0,) * 5)
        version = read_pool_version(api, world["pool"]["id"])
        world["draw"] = get_success_data(api.create_regrind_reincorporation(
            run_z["id"],
            {"pool_id": world["pool"]["id"], "kg": 100.0,
             "expected_regrind_pool_version": version},
            EXTRUDER))
        world["run_z"] = get_success_data(
            api.complete_extrusion_run(run_z["id"], 1000.0, 60.0, EXTRUDER))
        return world

    def test_nominal_and_as_built_figures_disagree_by_four_point_eight(self, api):
        """The recipe promises 26.000 pct; the run actually built 21.200 pct.

        PRD: "And `actual_recycled_content_pct` — the as-built variant — is
        `pcr_mass_kg` divided by `gross_output_kg`, multiplied by one hundred,
        rounded to three decimals."

        Design: Difficulty/dual_variant_calc/recycled_content_nominal_versus_as_built_diverge
        """
        world = self._two_runs(api)
        r3 = get_success_data(api.get_blend_recipe(world["r3"]["id"], ENGINEER))

        assert r3["nominal_recycled_content_pct"] == pytest.approx(26.000, abs=0.01)
        assert world["run_z"]["actual_recycled_content_pct"] == pytest.approx(21.200,
                                                                             abs=0.01)
        difference = (r3["nominal_recycled_content_pct"]
                      - world["run_z"]["actual_recycled_content_pct"])
        assert difference == pytest.approx(4.800, abs=0.01)

    def test_as_built_mass_balance_is_struck_from_the_drawn_regrind(self, api):
        """The draw feeds both the regrind ratio and the recycled mass.

        PRD: "`regrind_actual_pct` is `regrind_consumed_kg` divided by
        `gross_output_kg`, multiplied by one hundred, rounded to three decimals."

        Design: Difficulty/dual_variant_calc/recycled_content_nominal_versus_as_built_diverge
        """
        run_z = self._two_runs(api)["run_z"]

        assert run_z["regrind_consumed_kg"] == pytest.approx(100.000, abs=0.01)
        assert run_z["regrind_actual_pct"] == pytest.approx(10.000, abs=0.01)
        assert run_z["pcr_mass_kg"] == pytest.approx(212.000, abs=0.01)
        assert run_z["net_good_kg"] == pytest.approx(940.000, abs=0.01)
        assert run_z["status"] == "COMPLETED"

    def test_drawn_row_carries_the_pool_fraction_current_at_draw_time(self, api):
        """The 100.0 kg draw carries 50.000 kg of recycled mass with it.

        PRD: "so successive draws from a pool whose embedded fraction is shifting
        each carry the fraction current at their own draw time."

        Design: Difficulty/dual_variant_calc/recycled_content_nominal_versus_as_built_diverge
        """
        world = self._two_runs(api)
        txn = get_success_data(
            api.get_regrind_transaction(world["draw"]["id"], EXTRUDER))

        assert txn["direction"] == "OUT"
        assert txn["origin_kind"] == "REINCORPORATION"
        assert txn["kg"] == pytest.approx(100.000, abs=0.01)
        assert txn["pcr_kg"] == pytest.approx(50.000, abs=0.01)

    def test_pool_aggregates_reflect_both_generations(self, api):
        """Two inbound scrap rows and one outbound draw re-derive the pool.

        PRD: "`embedded_pcr_pct` is 0.000 when `cumulative_in_kg` is zero, and
        otherwise `cumulative_in_pcr_kg` divided by `cumulative_in_kg`,
        multiplied by one hundred, rounded to three decimals."

        Design: Difficulty/dual_variant_calc/recycled_content_nominal_versus_as_built_diverge
        """
        world = self._two_runs(api)
        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))

        assert pool["cumulative_in_kg"] == pytest.approx(160.000, abs=0.01)
        assert pool["cumulative_out_kg"] == pytest.approx(100.000, abs=0.01)
        assert pool["cumulative_in_pcr_kg"] == pytest.approx(62.720, abs=0.01)
        assert pool["available_kg"] == pytest.approx(60.000, abs=0.01)
        assert pool["embedded_pcr_pct"] == pytest.approx(39.200, abs=0.01)
        assert_pool_mass_invariants(pool)

    def test_the_all_pcr_first_run_matches_its_own_nominal_figure(self, api):
        """With no regrind drawn, nominal and as-built coincide at 50.000 pct.

        PRD: "`pcr_mass_kg` is then the virgin feed mass multiplied by the
        recipe's `virgin_pcr_pct` divided by one hundred, plus that pool-borne
        recycled mass, rounded to three decimals."

        Design: Difficulty/dual_variant_calc/recycled_content_nominal_versus_as_built_diverge
        """
        world = self._two_runs(api)
        r6 = get_success_data(api.get_blend_recipe(world["r6"]["id"], ENGINEER))

        assert world["run_y"]["actual_recycled_content_pct"] == pytest.approx(50.000,
                                                                             abs=0.01)
        assert r6["nominal_recycled_content_pct"] == pytest.approx(50.000, abs=0.01)
