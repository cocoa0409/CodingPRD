"""The four-link electrical chain: unit ceilings, busway ceilings, feed gates."""
import pytest

from test_helpers import (
    api_client,
    assert_hall_power_ledger_balances,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    EC,
    add_powered_rack,
    advance_phase,
    commission_pdu,
    create_busway,
    create_hall,
    create_pdu,
    create_rack,
    energize_busway,
    install_rack,
    prove_zone_and_cooling,
    read_busway,
    read_feed,
    read_hall,
    read_pdu,
    read_rack,
    reserve_feed,
    set_clock,
    setup_fit_out_hall,
    setup_planning_hall,
)


class TestBuswayNestedMinimum:
    """usable_kw is a nested min() over a topology-branched trunk term and an
    independent upstream ceiling."""

    def _hall_with_one_unit(self):
        set_clock("2026-08-01T00:00:00Z")
        hall = create_hall(
            "HC1",
            name="Data Hall C",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=900.00,
            gross_area_sqm=900.0,
            planned_rack_count=20,
        )
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        return hall, pdu

    def test_three_topologies_land_on_different_sides_of_the_minimum(self):
        """Three busway runs differing only in rated_amps and redundancy_topology
        under one 300.00 kW unit resolve to three different ceilings, because the
        min() is taken between a topology-scaled trunk term and the unit ceiling.

        PRD: "raw capacity multiplied by the continuous-load factor 0.80 and then
        by the topology factor, and the base figure is the smaller of that trunk
        figure and the upstream ceiling. The minimum is taken over unrounded
        operands; rounding before the comparison is wrong."

        Design: Difficulty/combinatorial_formula/busway_usable_kw_nested_min_with_topology_branch
        """
        hall, pdu = self._hall_with_one_unit()

        big = create_busway(
            pdu["id"], "BW-BIG", rated_amps=800, voltage_v=415, redundancy_topology="N"
        )
        mid = create_busway(
            pdu["id"],
            "BW-MID",
            rated_amps=400,
            voltage_v=415,
            redundancy_topology="N_PLUS_1",
        )
        two_n = create_busway(
            pdu["id"],
            "BW-2N",
            rated_amps=400,
            voltage_v=415,
            redundancy_topology="TWO_N",
        )

        assert big["raw_kw"] == pytest.approx(546.273, abs=0.0005), (
            "800 A at 415 V raw three-phase capacity"
        )
        assert big["usable_kw"] == pytest.approx(240.00, abs=0.005), (
            "the 300.00 kW unit ceiling binds the 800 A run, not its trunk term"
        )
        assert mid["raw_kw"] == pytest.approx(273.136, abs=0.0005)
        assert mid["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "the N_PLUS_1 trunk term binds below the 240.000 unit ceiling"
        )
        assert two_n["raw_kw"] == pytest.approx(273.136, abs=0.0005), (
            "TWO_N shares the 400 A trunk of the N_PLUS_1 run"
        )
        assert two_n["usable_kw"] == pytest.approx(109.25, abs=0.005), (
            "the TWO_N topology factor of 0.50 halves the same trunk term"
        )
        assert read_pdu(pdu["id"])["usable_cap_kw"] == pytest.approx(
            240.000, abs=0.0005
        ), "the unit publishes its nameplate times the continuous-load factor"

    def test_usable_ceiling_is_not_linear_in_amps_or_topology_factor(self):
        """The published ceiling of the TWO_N run is not half the ceiling of the
        800 A run, because the two runs are bound by different terms of the same
        nested minimum.

        PRD: "A topology factor is selected from the run's `redundancy_topology`:
        1.00 for `N`, 0.90 for `N_PLUS_1`, and 0.50 for `TWO_N`."

        Design: Difficulty/combinatorial_formula/busway_usable_kw_nested_min_with_topology_branch
        """
        hall, pdu = self._hall_with_one_unit()
        big = create_busway(
            pdu["id"], "BW-BIG", rated_amps=800, voltage_v=415, redundancy_topology="N"
        )
        mid = create_busway(
            pdu["id"],
            "BW-MID",
            rated_amps=400,
            voltage_v=415,
            redundancy_topology="N_PLUS_1",
        )
        two_n = create_busway(
            pdu["id"],
            "BW-2N",
            rated_amps=400,
            voltage_v=415,
            redundancy_topology="TWO_N",
        )

        assert mid["usable_kw"] != pytest.approx(big["usable_kw"] * 0.50, abs=0.005), (
            "halving the trunk of a unit-bound run does not give the mid run's ceiling"
        )
        assert two_n["usable_kw"] != pytest.approx(big["usable_kw"] * 0.50, abs=0.005), (
            "the ceiling is not a linear function of the topology factor alone"
        )
        assert two_n["usable_variant"] == "DESIGN", (
            "a run created while its hall is in PLANNING records the DESIGN variant"
        )
        assert two_n["committed_kw"] == pytest.approx(0.000, abs=0.0005)
        assert two_n["feed_count"] == 0
        assert two_n["status"] == "INSTALLED", "a new run sits at INSTALLED"
        assert read_hall(hall["id"])["status"] == "PLANNING", (
            "busway creation is not gated on the hall having left PLANNING"
        )


class TestDesignVersusCommissionedVariant:
    """The phase advance into COMMISSIONING re-reads every busway ceiling under the
    measured derate, so two runs with identical ratings diverge."""

    def _fit_out_hall_with_split_derates(self):
        ctx = setup_fit_out_hall(
            "HA1",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
            derate_a=0.94,
            derate_b=1.00,
            cu_rated_sensible_kw=120.00,
            cu_design_airflow_cfm=22000,
            cu_supply_delta_t_f=18.0,
        )
        prove_zone_and_cooling(ctx)
        add_powered_rack(ctx, design_kw=15.00, feed_kw=7.50, asset_tag="AT-0001")
        return ctx

    def test_advance_to_commissioning_diverges_two_identically_rated_runs(self):
        """Two 400 A / 415 V / N_PLUS_1 runs whose upstream units measured 0.94 and
        1.00 publish the same DESIGN ceiling, then split by exactly 11.80 kW once the
        hall enters COMMISSIONING and the variant flips.

        PRD: "Under the `COMMISSIONED` variant, `usable_kw` is the base figure
        multiplied by the upstream unit's `measured_derate_factor` and then rounded
        to two decimal places."

        Design: Difficulty/dual_variant_calc/busway_usable_kw_design_vs_commissioned_divergence
        """
        ctx = self._fit_out_hall_with_split_derates()

        before_a = read_busway(ctx["bw_a"]["id"])
        before_b = read_busway(ctx["bw_b"]["id"])
        assert before_a["usable_variant"] == "DESIGN"
        assert before_a["usable_kw"] == pytest.approx(196.66, abs=0.005)
        assert before_b["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "at design time the measured derate is ignored, so the two runs agree"
        )

        hall = advance_phase(ctx["hall_id"], "COMMISSIONING")
        assert hall["status"] == "COMMISSIONING"

        after_a = read_busway(ctx["bw_a"]["id"])
        after_b = read_busway(ctx["bw_b"]["id"])
        assert after_a["usable_variant"] == "COMMISSIONED"
        assert after_b["usable_variant"] == "COMMISSIONED"
        assert after_a["usable_kw"] == pytest.approx(184.86, abs=0.005), (
            "0.94 applied to the unrounded base figure 196.658208 gives 184.86"
        )
        assert after_b["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "a measured derate of 1.00 leaves the ceiling where design time put it"
        )
        assert after_b["usable_kw"] - after_a["usable_kw"] == pytest.approx(
            11.80, abs=0.005
        ), "the two variants of the same nameplate differ by exactly 11.80 kW"
        assert after_a["raw_kw"] == pytest.approx(273.136, abs=0.0005), (
            "the raw three-phase capacity is variant-independent"
        )
        assert after_b["raw_kw"] == pytest.approx(273.136, abs=0.0005)

    def test_variant_flip_moves_no_power_ledger_figure(self):
        """The variant flip lowers a ceiling but leaves committed_kw, the reserve and
        spare untouched, because those depend only on feed reservations.

        PRD: "though the variant flip changes neither `committed_kw` nor
        `commissioning_reserve_kw`, since those depend only on feed reservations."

        Design: Difficulty/dual_variant_calc/busway_usable_kw_design_vs_commissioned_divergence
        """
        ctx = self._fit_out_hall_with_split_derates()
        before = read_hall(ctx["hall_id"])

        advance_phase(ctx["hall_id"], "COMMISSIONING")
        after = read_hall(ctx["hall_id"])

        assert after["committed_kw"] == pytest.approx(15.00, abs=0.005), (
            "the two 7.50 kW feeds are the only commitment against the hall"
        )
        assert after["committed_kw"] == pytest.approx(before["committed_kw"], abs=0.005)
        assert after["commissioning_reserve_kw"] == pytest.approx(
            before["commissioning_reserve_kw"], abs=0.005
        )
        assert after["spare_kw"] == pytest.approx(360.00, abs=0.005)
        assert_hall_power_ledger_balances(after)
        assert read_busway(ctx["bw_a"]["id"])["committed_kw"] == pytest.approx(
            7.500, abs=0.0005
        ), "the derated run still carries the feed it carried before the flip"
        assert read_rack(ctx["rack_1"]["id"])["status"] == "POWERED", (
            "the rack that was legal at design time stays powered"
        )


class TestBuswayCeilingEquality:
    """The run-ceiling gate is a not-greater-than comparison, so a feed that lands
    exactly on the published ceiling is admitted and the next cent is not."""

    def _fit_out_hall_with_two_positions(self):
        ctx = setup_fit_out_hall("HM1", design_kw_capacity=400.00)
        ctx["rack_big"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=200.00,
            required_feed_count=1,
        )
        ctx["rack_small"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            2,
            design_kw=10.00,
            required_feed_count=1,
        )
        return ctx

    def test_feed_at_exactly_the_usable_ceiling_is_admitted(self):
        """A 196.66 kW reservation against a run whose usable_kw is 196.66 succeeds,
        and the following 0.01 kW request on the same run is refused on the run
        ceiling rather than on the breaker.

        PRD: "The run's current `committed_kw` plus this feed's `allocated_kw` must
        not exceed the run's `usable_kw` as computed under the run's current
        `usable_variant`. A breach is `ERR_BUSWAY_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/busway_capacity_equality_admits_feed_at_exact_usable_kw
        """
        ctx = self._fit_out_hall_with_two_positions()
        assert read_busway(ctx["bw_a"]["id"])["usable_kw"] == pytest.approx(
            196.66, abs=0.005
        )

        admitted = validate_success(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack_big"]["id"],
                    "busway_id": ctx["bw_a"]["id"],
                    "feed_side": "A",
                    "requested_kw": 196.66,
                    "breaker_amps": 400,
                },
                EC,
            ),
            201,
        )
        assert admitted["allocated_kw"] == pytest.approx(196.660, abs=0.0005), (
            "the stored allocation is the request at three decimal places"
        )
        assert admitted["status"] == "RESERVED"

        refused = api_client.create_rack_feed(
            {
                "rack_id": ctx["rack_small"]["id"],
                "busway_id": ctx["bw_a"]["id"],
                "feed_side": "A",
                "requested_kw": 0.01,
                "breaker_amps": 32,
            },
            EC,
        )
        validate_error(refused, ApiErrorId.ERR_BUSWAY_CAPACITY_EXCEEDED.value, 422)

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["committed_kw"] == pytest.approx(196.660, abs=0.0005)
        assert busway["feed_count"] == 1, "the refused request left no reservation"
        assert busway["raw_kw"] == pytest.approx(273.136, abs=0.0005)
        assert read_rack(ctx["rack_big"]["id"])["connected_kw"] == pytest.approx(
            196.660, abs=0.0005
        )
        assert read_rack(ctx["rack_small"]["id"])["connected_kw"] == pytest.approx(
            0.000, abs=0.0005
        )

    def test_ceiling_admission_steps_the_room_reserve_tier_up(self):
        """The admitted boundary reservation carries the room from the first reserve
        tier to the second, and the ledger still sums to the design capacity.

        PRD: "Committed load at or below 100.00 kW holds a reserve of 25.00 kW;
        committed load above 100.00 kW but at or below 250.00 kW holds a reserve of
        50.00 kW; committed load above 250.00 kW holds a reserve of 75.00 kW."

        Design: Difficulty/boundary_precision_check/busway_capacity_equality_admits_feed_at_exact_usable_kw
        """
        ctx = self._fit_out_hall_with_two_positions()
        validate_success(
            api_client.create_rack_feed(
                {
                    "rack_id": ctx["rack_big"]["id"],
                    "busway_id": ctx["bw_a"]["id"],
                    "feed_side": "A",
                    "requested_kw": 196.66,
                    "breaker_amps": 400,
                },
                EC,
            ),
            201,
        )
        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(196.66, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(50.00, abs=0.005), (
            "196.66 kW committed sits in the second tier"
        )
        assert hall["spare_kw"] == pytest.approx(153.34, abs=0.005)
        assert_hall_power_ledger_balances(hall)


class TestRackPowerOnNeedsBothPaths:
    """Powering a dual-corded position walks a three-link chain: both runs energised,
    each run's parent unit commissioned first."""

    def _hall_with_one_energised_side(self):
        ctx = setup_planning_hall("HO1", commission_pdus=False)
        commission_pdu(ctx["pdu_a"]["id"], 1.00)
        advance_phase(ctx["hall_id"], "FIT_OUT")
        ctx["bw_a"] = energize_busway(ctx["bw_a"]["id"])
        prove_zone_and_cooling(ctx)
        rack = create_rack(ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=15.00)
        ctx["rack_1"] = rack
        ctx["feed_a"] = reserve_feed(rack["id"], ctx["bw_a"]["id"], "A", 7.50)
        ctx["feed_b"] = reserve_feed(rack["id"], ctx["bw_b"]["id"], "B", 7.50)
        install_rack(rack["id"], "AT-0001")
        return ctx

    def test_power_on_walks_the_unit_then_run_then_rack_chain(self):
        """With only the A side energised the power-on is refused, energising the B
        run is itself refused until its unit is commissioned, and only when the whole
        chain is complete does the position take load.

        PRD: "Every one of those feeds sits on a run whose status is `ENERGIZED`;
        otherwise `ERR_BUSWAY_NOT_ENERGIZED`."

        Design: Difficulty/cross_entity_state_dependency/rack_power_on_requires_both_feed_busways_energized
        """
        ctx = self._hall_with_one_energised_side()

        validate_error(
            api_client.power_on_rack(ctx["rack_1"]["id"], EC),
            ApiErrorId.ERR_BUSWAY_NOT_ENERGIZED.value,
            409,
        )
        validate_error(
            api_client.energize_busway(ctx["bw_b"]["id"], EC),
            ApiErrorId.ERR_PDU_NOT_COMMISSIONED.value,
            409,
        )

        pdu_b = commission_pdu(ctx["pdu_b"]["id"], 1.00)
        assert pdu_b["status"] == "COMMISSIONED"
        assert pdu_b["usable_cap_kw"] == pytest.approx(240.000, abs=0.0005)

        bw_b = energize_busway(ctx["bw_b"]["id"])
        assert bw_b["status"] == "ENERGIZED"
        assert bw_b["usable_kw"] == pytest.approx(196.66, abs=0.005)

        rack = validate_success(api_client.power_on_rack(ctx["rack_1"]["id"], EC), 200)
        assert rack["status"] == "POWERED"
        assert rack["energized_feed_count"] == 2
        assert read_feed(ctx["feed_a"]["id"])["status"] == "ENERGIZED"
        assert read_feed(ctx["feed_b"]["id"])["status"] == "ENERGIZED"

    def test_commissioning_the_second_unit_alone_does_not_admit_the_rack(self):
        """A commissioned unit whose run is still INSTALLED does not satisfy the
        power-on chain: the run itself must be ENERGIZED, and until then the position
        stays INSTALLED with no energised feeds.

        PRD: "On success the run's status becomes `ENERGIZED` and its `usable_kw` is
        recomputed under the variant the hall's current phase selects."

        Design: Difficulty/cross_entity_state_dependency/rack_power_on_requires_both_feed_busways_energized
        """
        ctx = self._hall_with_one_energised_side()
        commission_pdu(ctx["pdu_b"]["id"], 1.00)

        assert read_busway(ctx["bw_b"]["id"])["status"] == "INSTALLED"
        validate_error(
            api_client.power_on_rack(ctx["rack_1"]["id"], EC),
            ApiErrorId.ERR_BUSWAY_NOT_ENERGIZED.value,
            409,
        )
        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "INSTALLED"
        assert rack["energized_feed_count"] == 0
        assert read_feed(ctx["feed_b"]["id"])["status"] == "RESERVED"

        energize_busway(ctx["bw_b"]["id"])
        powered = validate_success(
            api_client.power_on_rack(ctx["rack_1"]["id"], EC), 200
        )
        assert powered["status"] == "POWERED"
        hall = read_hall(ctx["hall_id"])
        assert hall["custody_ops_count"] == 1
        assert hall["custody_fitout_count"] == 0
        assert hall["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert hall["thermal_load_kw"] == pytest.approx(12.75, abs=0.005), (
            "15.00 kW of designed density at the diversity factor 0.85"
        )
        assert hall["thermal_posture"] == "NOMINAL"
