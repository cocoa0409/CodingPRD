"""Boundary behaviour of the derived-figure arithmetic: which rows a roll-up may
count, which machines a capacity variant may count, and where a graded threshold
sits exactly on its own edge."""
import pytest

from test_helpers import (
    api_client,
    assert_hall_power_ledger_balances,
    validate_paginated,
)
from test_helpers.constants import USER_IDS
from test_helpers.fixtures import (
    CM,
    OM,
    SA,
    approve_mop,
    approve_script,
    commission_cooling_unit,
    commission_device,
    complete_load_bank,
    create_cage,
    create_camera,
    create_card_reader,
    create_cooling_unit,
    create_hall,
    create_mop,
    create_package,
    create_packet,
    create_rack,
    create_tenant,
    install_rack,
    place_unit_in_service,
    power_on_rack,
    prove_zone_and_cooling,
    read_busway,
    read_cage,
    read_capacity_summary,
    read_cooling_unit,
    read_hall,
    read_mop,
    read_package,
    read_packet,
    read_rack,
    reserve_feed,
    schedule_load_bank,
    set_clock,
    setup_commissioning_hall,
    setup_fit_out_hall,
    setup_planning_hall,
    start_load_bank,
    submit_mop,
    tag_rack,
)


class TestChargeableRollUpScope:
    """A position's own uplifted figure is fixed at placement, but the hall's roll-up
    counts only the positions that have actually been installed."""

    def _hall_with_one_installed_and_one_planned_position(self):
        ctx = setup_fit_out_hall("CX42", design_kw_capacity=400.00)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=10.00
        )
        ctx["rack_2"] = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 2, design_kw=10.00
        )
        ctx["rack_1"] = install_rack(ctx["rack_1"]["id"], "AT-0042")
        return ctx

    def test_planned_position_carries_its_figure_yet_is_left_out_of_the_roll_up(self):
        """Two 10.00 kW positions each publish 10.45 kW, but with only one installed the
        hall's chargeable roll-up stands at 10.45 kW, not 20.90 kW.

        PRD: "The hall's `chargeable_kw` is the sum of the per-rack figures over every
        rack of the hall whose status is `INSTALLED`, `POWERED`, `AT_RISK` or
        `RELEASED`, rounded again to two decimal places (a no-op when every term is
        already at two places). `PLANNED` positions never contribute."

        Design: Corner/calculations/rack_chargeable_rollup_excludes_planned_racks
        """
        ctx = self._hall_with_one_installed_and_one_planned_position()
        installed = read_rack(ctx["rack_1"]["id"])
        planned = read_rack(ctx["rack_2"]["id"])
        assert installed["status"] == "INSTALLED"
        assert planned["status"] == "PLANNED"
        assert installed["chargeable_kw"] == pytest.approx(10.45, abs=0.005)
        assert planned["chargeable_kw"] == pytest.approx(10.45, abs=0.005), (
            "the per-rack figure is fixed at placement, whatever the status"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["chargeable_kw"] == pytest.approx(10.45, abs=0.005), (
            "only the installed position is inside the roll-up's scope"
        )
        assert hall["chargeable_kw"] != pytest.approx(20.90, abs=0.005), (
            "counting the planned position would have doubled the figure"
        )
        assert hall["rack_total_count"] == 2, (
            "the planned position still occupies floor space"
        )
        assert hall["custody_fitout_count"] == 2
        assert hall["custody_ops_count"] == 0

    def test_installing_the_second_position_adds_exactly_its_own_rounded_figure(self):
        """Installing the planned position brings the roll-up from 10.45 kW to 20.90 kW
        — the sum of two already-rounded per-rack figures.

        PRD: "Each rack's own `chargeable_kw` is computed first, individually, as its
        designed density multiplied by 1.045 and rounded half up to two decimal places.
        Only then are those per-rack figures summed."

        Design: Corner/calculations/rack_chargeable_rollup_excludes_planned_racks
        """
        ctx = self._hall_with_one_installed_and_one_planned_position()
        assert read_hall(ctx["hall_id"])["chargeable_kw"] == pytest.approx(
            10.45, abs=0.005
        )

        second = install_rack(ctx["rack_2"]["id"], "AT-0043")
        assert second["status"] == "INSTALLED"

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["chargeable_kw"] == pytest.approx(20.90, abs=0.005)
        assert summary["thermal_load_kw"] == pytest.approx(0.00, abs=0.005), (
            "an installed position that has not been powered on draws no heat"
        )
        assert summary["committed_kw"] == pytest.approx(0.00, abs=0.005), (
            "the roll-up is a commercial figure and moves no electrical pool"
        )
        assert summary["custody_fitout_count"] == 2
        assert summary["custody_ops_count"] == 0


class TestDutySetMembership:
    """Only a unit that has been placed into duty contributes to either capacity
    variant; a commissioned machine still on the pad contributes nothing."""

    def _hall_with_one_duty_unit_and_one_commissioned_spare(self):
        ctx = setup_fit_out_hall(
            "CX43",
            cooling_redundancy="N",
            cu_rated_sensible_kw=120.00,
            cu_design_airflow_cfm=22000,
            cu_supply_delta_t_f=18.0,
        )
        prove_zone_and_cooling(ctx, measured_leakage_pct=5.00)
        ctx["cu_2"] = create_cooling_unit(
            ctx["hall_id"],
            "CU-2",
            rated_sensible_kw=80.00,
            design_airflow_cfm=12000,
            supply_delta_t_f=18.0,
            redundancy_role="REDUNDANT",
        )
        ctx["cu_2"] = commission_cooling_unit(ctx["cu_2"]["id"], 12000)
        return ctx

    def test_commissioned_unit_carries_its_own_figure_but_not_the_hall_s(self):
        """CU-2 publishes its own 64.95193 kW airflow figure the moment it is
        commissioned, yet the hall still reads 120.00 kW nameplate and 119.08 kW
        airflow — CU-1's numbers alone.

        PRD: "The duty set is every cooling unit of the hall whose status is
        `IN_SERVICE`; units at `MAINTENANCE`, `COMMISSIONED` or `INSTALLED` are
        excluded."

        Design: Corner/calculations/hall_cooling_model_excludes_commissioned_unit_not_in_service
        """
        ctx = self._hall_with_one_duty_unit_and_one_commissioned_spare()
        spare = read_cooling_unit(ctx["cu_2"]["id"])
        assert spare["status"] == "COMMISSIONED"
        assert spare["airflow_capacity_kw"] == pytest.approx(64.95193, abs=0.000005), (
            "12000 cfm at five percent leakage and an 18.0 F delta-T"
        )
        duty = read_cooling_unit(ctx["cu_1"]["id"])
        assert duty["status"] == "IN_SERVICE"
        assert duty["airflow_capacity_kw"] == pytest.approx(119.07855, abs=0.000005)

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["cooling_capacity_nameplate_kw"] == pytest.approx(
            120.00, abs=0.005
        ), "80.00 kW sitting at COMMISSIONED is outside the duty set"
        assert summary["cooling_capacity_airflow_kw"] == pytest.approx(
            119.08, abs=0.005
        )
        assert summary["cooling_capacity_kw"] == pytest.approx(119.08, abs=0.005), (
            "the airflow variant is the smaller of the two and therefore binds"
        )
        assert summary["worst_leakage_pct"] == pytest.approx(5.00, abs=0.005)
        assert summary["thermal_load_kw"] == pytest.approx(0.00, abs=0.005)
        assert summary["cooling_margin_kw"] == pytest.approx(119.08, abs=0.005)
        assert summary["thermal_posture"] == "NOMINAL"

    def test_placing_the_spare_into_duty_is_what_admits_its_capacity(self):
        """The very same machine lifts the hall to 200.00 kW nameplate and 184.03 kW
        airflow once it is placed in service, which is the proof that its exclusion was
        about duty status and nothing else.

        PRD: "Placing a commissioned unit into duty advances it `COMMISSIONED →
        IN_SERVICE` and re-derives the hall cooling model, because only now does the
        unit contribute to either capacity variant."

        Design: Corner/calculations/hall_cooling_model_excludes_commissioned_unit_not_in_service
        """
        ctx = self._hall_with_one_duty_unit_and_one_commissioned_spare()
        before = read_capacity_summary(ctx["hall_id"])
        assert before["cooling_capacity_kw"] == pytest.approx(119.08, abs=0.005)

        promoted = place_unit_in_service(ctx["cu_2"]["id"])
        assert promoted["status"] == "IN_SERVICE"

        after = read_capacity_summary(ctx["hall_id"])
        assert after["cooling_capacity_nameplate_kw"] == pytest.approx(
            200.00, abs=0.005
        ), "120.00 plus 80.00 with nothing withheld under an N stance"
        assert after["cooling_capacity_airflow_kw"] == pytest.approx(
            184.03, abs=0.005
        ), "119.07855 plus 64.95193 is 184.03048 before publication rounding"
        assert after["cooling_capacity_kw"] == pytest.approx(184.03, abs=0.005)
        assert after["cooling_margin_kw"] == pytest.approx(184.03, abs=0.005)


class TestNPlusOneWithholdsTheLargestDutyUnit:
    """Under an N_PLUS_1 stance both capacity variants hold back the single largest
    contribution, so a hall running one machine publishes no capacity at all."""

    def _n_plus_one_hall_with_a_single_duty_unit(self):
        ctx = setup_fit_out_hall(
            "CX44",
            cooling_redundancy="N_PLUS_1",
            cu_rated_sensible_kw=120.00,
            cu_design_airflow_cfm=22000,
            cu_supply_delta_t_f=18.0,
        )
        prove_zone_and_cooling(ctx, measured_leakage_pct=5.00)
        return ctx

    def _second_duty_unit(self, ctx):
        unit = create_cooling_unit(
            ctx["hall_id"],
            "CU-2",
            rated_sensible_kw=80.00,
            design_airflow_cfm=12000,
            supply_delta_t_f=18.0,
            redundancy_role="REDUNDANT",
        )
        commission_cooling_unit(unit["id"], 12000)
        ctx["cu_2"] = place_unit_in_service(unit["id"])
        return ctx

    def test_a_single_duty_unit_withholds_itself_and_leaves_no_capacity(self):
        """With CU-1 alone in duty the largest contribution is CU-1 itself, so nameplate
        and airflow capacity both publish 0.00 kW even though the machine is running.

        PRD: "When the hall's `cooling_redundancy` is `N_PLUS_1` and the duty set is
        non-empty, the largest single `rated_sensible_kw` in the duty set is subtracted
        from that gross figure; when the stance is `N`, nothing is subtracted."

        Design: Corner/calculations/hall_cooling_model_n_plus_one_subtracts_largest_duty_unit
        """
        ctx = self._n_plus_one_hall_with_a_single_duty_unit()
        assert read_cooling_unit(ctx["cu_1"]["id"])["status"] == "IN_SERVICE"
        assert read_cooling_unit(ctx["cu_1"]["id"])[
            "airflow_capacity_kw"
        ] == pytest.approx(119.07855, abs=0.000005)

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["cooling_capacity_nameplate_kw"] == pytest.approx(
            0.00, abs=0.005
        ), "120.00 gross less the 120.00 largest duty unit"
        assert summary["cooling_capacity_airflow_kw"] == pytest.approx(
            0.00, abs=0.005
        ), "119.07855 gross less the 119.07855 largest per-unit figure"
        assert summary["cooling_capacity_kw"] == pytest.approx(0.00, abs=0.005)
        assert summary["cooling_margin_kw"] == pytest.approx(0.00, abs=0.005)
        assert summary["thermal_posture"] == "NOMINAL", (
            "a margin of exactly 0.00 is still nominal"
        )

    def test_the_second_unit_is_what_the_hall_may_actually_publish(self):
        """Adding an 80.00 kW machine to duty leaves the hall publishing 80.00 kW
        nameplate and 64.95 kW airflow — the smaller machine's figures, because the
        larger one is the withheld spare.

        PRD: "Gross airflow capacity is the sum of those per-unit figures across the
        duty set, and — exactly as in the nameplate variant — when `cooling_redundancy`
        is `N_PLUS_1` and the duty set is non-empty the largest single per-unit figure
        is subtracted."

        Design: Corner/calculations/hall_cooling_model_n_plus_one_subtracts_largest_duty_unit
        """
        ctx = self._n_plus_one_hall_with_a_single_duty_unit()
        self._second_duty_unit(ctx)

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["cooling_capacity_nameplate_kw"] == pytest.approx(
            80.00, abs=0.005
        ), "200.00 gross less the 120.00 largest duty unit"
        assert summary["cooling_capacity_airflow_kw"] == pytest.approx(
            64.95, abs=0.005
        ), "184.03048 gross less 119.07855 is 64.95193 before publication rounding"
        assert summary["cooling_capacity_kw"] == pytest.approx(64.95, abs=0.005), (
            "the airflow variant remains the smaller of the two"
        )
        assert summary["cooling_margin_kw"] == pytest.approx(64.95, abs=0.005)
        assert summary["thermal_posture"] == "NOMINAL"
        assert summary["worst_leakage_pct"] == pytest.approx(5.00, abs=0.005)


class TestDistinctReaderZoneCounting:
    """Two card readers arming the same access-control zone are one zone, so a cage can
    reach full camera coverage and still be short of its reader-zone floor."""

    def _cage_with_two_readers_on_one_zone(self):
        hall = create_hall("CX45", tenant_mode="MULTI_TENANT")
        tenant = create_tenant("CXT45", contracted_kw=100.00)
        cage = create_cage(hall["id"], tenant["id"], "CG-1", perimeter_length_m=40.0)
        camera = create_camera(cage["id"], "CAM-1", 38.0)
        reader_1 = create_card_reader(cage["id"], "RDR-N1", "Z-N")
        reader_2 = create_card_reader(cage["id"], "RDR-N2", "Z-N")
        commission_device(camera["id"])
        commission_device(reader_1["id"])
        commission_device(reader_2["id"])
        return {
            "hall": hall,
            "tenant": tenant,
            "cage": cage,
            "camera": camera,
            "reader_1": reader_1,
            "reader_2": reader_2,
        }

    def test_two_readers_on_one_zone_count_once_and_hold_the_cage_in_fit_out(self):
        """Camera coverage reaches exactly its 95.00 floor while the two same-zone
        readers publish an active zone count of 1 against a floor of 2, so the cage
        stays at FIT_OUT.

        PRD: "`active_reader_zone_count` is the number of **distinct**
        `reader_zone_label` values among the cage's `ACTIVE` card readers — two readers
        arming the same zone count once."

        Design: Corner/calculations/cage_security_coverage_counts_distinct_reader_zones_only
        """
        ctx = self._cage_with_two_readers_on_one_zone()
        cage = read_cage(ctx["cage"]["id"])
        assert cage["camera_coverage_pct"] == pytest.approx(95.00, abs=0.005), (
            "38.0 metres seen of a 40.0 metre perimeter is 95.00 percent"
        )
        assert cage["required_camera_coverage_pct"] == pytest.approx(95.00, abs=0.005)
        assert cage["active_reader_zone_count"] == 1, (
            "RDR-N1 and RDR-N2 both arm Z-N, which is one distinct zone"
        )
        assert cage["required_reader_zone_count"] == 2
        assert cage["operational_status"] == "FIT_OUT", (
            "the conjunction fails on the reader-zone floor alone"
        )

        rows, meta = validate_paginated(
            api_client.list_security_devices(
                SA, {"cage_id": ctx["cage"]["id"], "device_type": "CARD_READER"}
            )
        )
        assert meta["total_count"] == 2, "both readers exist and are addressable"
        assert all(row["status"] == "ACTIVE" for row in rows), (
            "both readers were commissioned, so both are ACTIVE"
        )
        assert {row["reader_zone_label"] for row in rows} == {"Z-N"}

    def test_a_reader_in_a_second_zone_completes_the_conjunction(self):
        """Commissioning a reader that arms Z-S lifts the distinct count to 2 and the
        cage advances FIT_OUT to SECURED in that same request.

        PRD: "When the re-derived coverage reaches or exceeds
        `required_camera_coverage_pct` and the re-derived distinct reader-zone count
        reaches or exceeds `required_reader_zone_count`, and the cage is still at
        `FIT_OUT`, the cage advances `FIT_OUT → SECURED` in that same request."

        Design: Corner/calculations/cage_security_coverage_counts_distinct_reader_zones_only
        """
        ctx = self._cage_with_two_readers_on_one_zone()
        assert read_cage(ctx["cage"]["id"])["operational_status"] == "FIT_OUT"

        third = create_card_reader(ctx["cage"]["id"], "RDR-S1", "Z-S")
        assert read_cage(ctx["cage"]["id"])["active_reader_zone_count"] == 1, (
            "a PLANNED reader contributes nothing to the zone count"
        )

        commission_device(third["id"])
        cage = read_cage(ctx["cage"]["id"])
        assert cage["active_reader_zone_count"] == 2, "Z-N and Z-S are two zones"
        assert cage["camera_coverage_pct"] == pytest.approx(95.00, abs=0.005)
        assert cage["operational_status"] == "SECURED", (
            "95.00 against 95.00 is inclusive, and 2 zones meets the floor of 2"
        )


class TestAssetTagCompletionOverAPartialScope:
    """One tagged cabinet out of three in scope is 33.33 percent complete, and the
    figure is re-derived while the packet is still under assembly."""

    def _cage_with_three_powered_racks_one_tagged(self):
        ctx = setup_fit_out_hall(
            "CX46", tenant_mode="MULTI_TENANT", design_kw_capacity=400.00
        )
        prove_zone_and_cooling(ctx, measured_leakage_pct=5.00)
        tenant = create_tenant("CXT46", contracted_kw=100.00)
        cage = create_cage(ctx["hall_id"], tenant["id"], "CG-1", perimeter_length_m=40.0)
        ctx["tenant"], ctx["cage"] = tenant, cage
        for index in (1, 2, 3):
            rack = create_rack(
                ctx["hall_id"],
                ctx["zone_id"],
                "A",
                index,
                design_kw=5.00,
                required_feed_count=1,
                cage_id=cage["id"],
                tenant_id=tenant["id"],
            )
            ctx[f"rack_{index}"] = rack
            reserve_feed(rack["id"], ctx["bw_a"]["id"], "A", 5.00, 32)
            install_rack(rack["id"], "AT-0001" if index == 1 else None)
            ctx[f"rack_{index}"] = power_on_rack(rack["id"])
        return ctx

    def test_one_tagged_rack_of_three_in_scope_reads_thirty_three_percent(self):
        """All three powered cabinets are in scope, only the first carries an asset tag,
        and the packet opens at 33.33 percent with 15.69 kW of released load.

        PRD: "And `asset_tag_completion_pct` is the share of the in-scope set that
        carries an `asset_tag` — a rack counts as tagged only when its `asset_tag` is
        neither null nor the empty string — expressed as the tagged count divided by
        `rack_in_scope_count`, multiplied by 100, rounded to two decimal places."

        Design: Corner/calculations/asset_tag_completion_partial_scope_yields_thirty_three_percent
        """
        ctx = self._cage_with_three_powered_racks_one_tagged()
        assert read_rack(ctx["rack_1"]["id"])["asset_tag"] == "AT-0001"
        assert read_rack(ctx["rack_2"]["id"])["asset_tag"] is None
        assert read_rack(ctx["rack_3"]["id"])["asset_tag"] is None

        packet = create_packet(ctx["hall_id"], ctx["cage"]["id"], "AB-0046")
        assert packet["status"] == "DRAFT"
        assert packet["rack_in_scope_count"] == 3, "all three cabinets are POWERED"
        assert packet["asset_tag_completion_pct"] == pytest.approx(33.33, abs=0.005), (
            "one of three tagged is 33.333... percent truncated by rounding to 33.33"
        )
        assert packet["released_kw"] == pytest.approx(15.69, abs=0.005), (
            "5.00 kW uplifted to 5.23 kW per cabinet, then summed over three"
        )

        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["chargeable_kw"] == pytest.approx(15.69, abs=0.005)
        assert summary["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert summary["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert summary["spare_kw"] == pytest.approx(360.00, abs=0.005)
        assert summary["thermal_load_kw"] == pytest.approx(12.75, abs=0.005)
        assert summary["custody_ops_count"] == 3
        assert_hall_power_ledger_balances(summary)

    def test_tagging_a_second_rack_lifts_the_draft_packet_to_sixty_six_percent(self):
        """Writing an asset tag onto the second cabinet re-derives the DRAFT packet's
        completion figure from 33.33 to 66.67 percent, while released load is unmoved.

        PRD: "Doing so re-derives the asset-tag completion figure of any release packet
        of that rack's cage that is still in `DRAFT`, since a packet under assembly must
        always reflect the current tagging reality."

        Design: Corner/calculations/asset_tag_completion_partial_scope_yields_thirty_three_percent
        """
        ctx = self._cage_with_three_powered_racks_one_tagged()
        packet = create_packet(ctx["hall_id"], ctx["cage"]["id"], "AB-0046")
        assert packet["asset_tag_completion_pct"] == pytest.approx(33.33, abs=0.005)

        tagged = tag_rack(ctx["rack_2"]["id"], "AT-0002")
        assert tagged["asset_tag"] == "AT-0002"

        refreshed = read_packet(packet["id"])
        assert refreshed["status"] == "DRAFT"
        assert refreshed["rack_in_scope_count"] == 3
        assert refreshed["asset_tag_completion_pct"] == pytest.approx(
            66.67, abs=0.005
        ), "two of three tagged is 66.666... percent rounded half up to 66.67"
        assert refreshed["released_kw"] == pytest.approx(15.69, abs=0.005), (
            "tagging is documentation and moves no load"
        )


class TestLedgerConservationAcrossAReservation:
    """The three ledger figures are re-derived together and always sum back to the
    hall's design capacity, whichever reserve tier the reservation lands in."""

    def _fit_out_hall_with_two_positions(self):
        ctx = setup_fit_out_hall("CX47", design_kw_capacity=400.00)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=40.00,
            required_feed_count=1,
        )
        ctx["rack_2"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            2,
            design_kw=70.00,
            required_feed_count=1,
        )
        return ctx

    def test_a_single_reservation_leaves_the_three_figures_summing_to_capacity(self):
        """A 40.00 kW reservation on a 400.00 kW room lands committed load at 40.00 kW,
        the first-tier reserve at 25.00 kW and spare at 335.00 kW — 400.00 kW exactly.

        PRD: "The hall power ledger balances: `committed_kw` plus
        `commissioning_reserve_kw` plus `spare_kw` always equals the hall's
        `design_kw_capacity`."

        Design: Corner/calculations/hall_power_ledger_conserves_design_capacity_after_reservation
        """
        ctx = self._fit_out_hall_with_two_positions()
        before = read_hall(ctx["hall_id"])
        assert before["committed_kw"] == pytest.approx(0.00, abs=0.005)
        assert before["spare_kw"] == pytest.approx(375.00, abs=0.005)
        assert_hall_power_ledger_balances(before)

        feed = reserve_feed(ctx["rack_1"]["id"], ctx["bw_a"]["id"], "A", 40.00, 100)
        assert feed["status"] == "RESERVED"
        assert feed["allocated_kw"] == pytest.approx(40.000, abs=0.0005), (
            "the request is stored rounded to three decimal places"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(40.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(335.00, abs=0.005)
        assert (
            hall["committed_kw"]
            + hall["commissioning_reserve_kw"]
            + hall["spare_kw"]
        ) == pytest.approx(400.00, abs=0.005), "the three figures reconcile exactly"
        assert_hall_power_ledger_balances(hall)

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["raw_kw"] == pytest.approx(273.136, abs=0.0005)
        assert busway["usable_variant"] == "DESIGN"
        assert busway["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "the trunk figure of 196.658208 binds under the 240.000 upstream ceiling"
        )
        assert busway["committed_kw"] == pytest.approx(40.000, abs=0.0005)
        assert busway["feed_count"] == 1
        assert read_rack(ctx["rack_1"]["id"])["connected_kw"] == pytest.approx(
            40.000, abs=0.0005
        )
        assert read_rack(ctx["rack_1"]["id"])["energized_feed_count"] == 0, (
            "a reserved feed is not yet an energised one"
        )

    def test_the_invariant_survives_a_reservation_that_steps_the_reserve_tier(self):
        """A second 70.00 kW reservation carries committed load past 100.00 kW, so the
        reserve steps to 50.00 kW and spare falls to 240.00 kW — still 400.00 kW in total.

        PRD: "`spare_kw` is the hall's `design_kw_capacity` less `committed_kw` less
        `commissioning_reserve_kw`, rounded to two decimal places."

        Design: Corner/calculations/hall_power_ledger_conserves_design_capacity_after_reservation
        """
        ctx = self._fit_out_hall_with_two_positions()
        reserve_feed(ctx["rack_1"]["id"], ctx["bw_a"]["id"], "A", 40.00, 100)
        reserve_feed(ctx["rack_2"]["id"], ctx["bw_a"]["id"], "A", 70.00, 200)

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(110.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(50.00, abs=0.005), (
            "committed load above 100.00 kW holds the second-tier reserve"
        )
        assert hall["spare_kw"] == pytest.approx(240.00, abs=0.005)
        assert_hall_power_ledger_balances(hall)

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["committed_kw"] == pytest.approx(110.000, abs=0.0005)
        assert busway["feed_count"] == 2
        assert busway["committed_kw"] <= busway["usable_kw"], (
            "110.000 kW sits well inside the run's 196.66 kW ceiling"
        )


class TestLoadBankGradingBoundaries:
    """Both limbs of the grading conjunction are inclusive: a run measured at exactly
    the five-percent tolerance and exactly 8.0 degrees passes, and a hair below either
    limb fails."""

    def _commissioning_hall_with_an_approved_script(self):
        ctx = setup_commissioning_hall("CX48")
        package = create_package(
            ctx["hall_id"], "L4", "L4 integrated systems test", target_load_kw=20.00
        )
        approve_script(package["id"], 1)
        ctx["package"] = package
        return ctx

    def test_exactly_nineteen_kilowatts_and_exactly_eight_degrees_both_pass(self):
        """A 20.00 kW run measured at 19.00 kW — precisely the rounded tolerance — with a
        return-air delta-T of exactly 8.0 degrees grades PASS.

        PRD: "Grading is a conjunction: the measured load must be at least the run's
        `target_kw` multiplied by 0.95 and rounded to two decimal places (a five percent
        tolerance), **and** the measured return-air delta-T must be at least 8.0 degrees
        Fahrenheit. Both satisfied gives `result` `PASS`; either short gives `FAIL`."

        Design: Corner/calculations/load_bank_result_tolerance_boundary_and_delta_t_floor
        """
        ctx = self._commissioning_hall_with_an_approved_script()
        assert read_hall(ctx["hall_id"])[
            "commissioning_reserve_kw"
        ] == pytest.approx(25.00, abs=0.005), (
            "the room lends 25.00 kW of reserve to a single 20.00 kW run"
        )

        run = schedule_load_bank(
            ctx["package"]["id"],
            20.00,
            "2026-08-05T02:00:00Z",
            "2026-08-05T06:00:00Z",
        )
        assert run["status"] == "SCHEDULED"
        assert run["result"] is None
        set_clock("2026-08-05T03:00:00Z")
        start_load_bank(run["id"])

        graded = complete_load_bank(run["id"], 19.00, 8.0)
        assert graded["status"] == "COMPLETED"
        assert graded["measured_kw"] == pytest.approx(19.00, abs=0.005)
        assert graded["measured_return_delta_t_f"] == pytest.approx(8.0, abs=0.05)
        assert graded["result"] == "PASS", (
            "20.00 times 0.95 is exactly 19.00, and the floor is 8.0 inclusive"
        )

        package = read_package(ctx["package"]["id"])
        assert package["measured_load_kw"] == pytest.approx(19.00, abs=0.005), (
            "the package records the highest measured load of its completed runs"
        )
        assert package["script_status"] == "SCRIPT_APPROVED", (
            "grading a run does not move the script dimension"
        )
        assert package["package_state"] == "IN_EXECUTION"

    def test_either_limb_short_of_its_floor_grades_the_run_a_failure(self):
        """The same 19.00 kW measurement fails at 7.9 degrees, and a 18.99 kW measurement
        fails at a comfortable 12.0 degrees — each limb is decisive on its own.

        PRD: "Both satisfied gives `result` `PASS`; either short gives `FAIL`."

        Design: Corner/calculations/load_bank_result_tolerance_boundary_and_delta_t_floor
        """
        ctx = self._commissioning_hall_with_an_approved_script()

        cold = schedule_load_bank(
            ctx["package"]["id"],
            20.00,
            "2026-08-05T02:00:00Z",
            "2026-08-05T06:00:00Z",
        )
        set_clock("2026-08-05T03:00:00Z")
        start_load_bank(cold["id"])
        graded_cold = complete_load_bank(cold["id"], 19.00, 7.9)
        assert graded_cold["result"] == "FAIL", (
            "7.9 degrees is short of the 8.0 degree floor"
        )
        assert graded_cold["measured_kw"] == pytest.approx(19.00, abs=0.005)

        light = schedule_load_bank(
            ctx["package"]["id"],
            20.00,
            "2026-08-07T02:00:00Z",
            "2026-08-07T06:00:00Z",
        )
        set_clock("2026-08-07T03:00:00Z")
        start_load_bank(light["id"])
        graded_light = complete_load_bank(light["id"], 18.99, 12.0)
        assert graded_light["result"] == "FAIL", (
            "18.99 kW is one hundredth short of the 19.00 kW tolerance"
        )

        package = read_package(ctx["package"]["id"])
        assert package["measured_load_kw"] == pytest.approx(19.00, abs=0.005), (
            "a failing run still contributes its measurement to the high-water mark"
        )
        assert package["script_status"] == "SCRIPT_APPROVED"


class TestApprovalRequirementDerivedFromRiskClass:
    """Submission is where the quorum requirement is fixed: two votes for a high-risk
    change, one for anything else."""

    def _hall_with_a_high_and_a_medium_risk_change(self):
        ctx = setup_planning_hall("CX49")
        ctx["mop_high"] = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            title="Isolate BW-A1 for tap-off works",
            risk_class="HIGH",
            window_start="2026-08-10T02:00:00Z",
            window_end="2026-08-10T06:00:00Z",
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        ctx["mop_medium"] = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_b"]["id"],
            title="Re-torque BW-B1 joints",
            risk_class="MEDIUM",
            window_start="2026-08-11T02:00:00Z",
            window_end="2026-08-11T06:00:00Z",
            author_user_id=USER_IDS["ELECTRICAL_CONTRACTOR"],
        )
        return ctx

    def test_high_risk_asks_for_two_votes_and_stays_under_review_after_one(self):
        """The high-risk change submits with a requirement of 2 while the medium-risk one
        submits with 1, and a single ChangeManager approval leaves the high-risk change at
        UNDER_REVIEW with an approval count of 1.

        PRD: "On success `required_approval_count` is derived: 2 for a `HIGH` risk MOP, 1
        for `LOW` or `MEDIUM`."

        Design: Corner/calculations/mop_approval_requirement_two_for_high_one_for_medium
        """
        ctx = self._hall_with_a_high_and_a_medium_risk_change()
        assert ctx["mop_high"]["required_approval_count"] == 0, (
            "a DRAFT MOP has not yet had its requirement derived"
        )

        high = submit_mop(
            ctx["mop_high"]["id"], USER_IDS["ELECTRICAL_CONTRACTOR"]
        )
        medium = submit_mop(
            ctx["mop_medium"]["id"], USER_IDS["ELECTRICAL_CONTRACTOR"]
        )
        assert high["status"] == "UNDER_REVIEW"
        assert high["required_approval_count"] == 2
        assert high["approval_count"] == 0
        assert medium["status"] == "UNDER_REVIEW"
        assert medium["required_approval_count"] == 1

        approve_mop(
            ctx["mop_high"]["id"],
            role_headers=CM,
            user_id=USER_IDS["CHANGE_MANAGER"],
        )
        after_one = read_mop(ctx["mop_high"]["id"])
        assert after_one["status"] == "UNDER_REVIEW", (
            "one vote of the two the requirement asks for is not a quorum"
        )
        assert after_one["approval_count"] == 1
        assert after_one["required_approval_count"] == 2

    def test_the_second_distinct_role_completes_the_high_risk_quorum(self):
        """A second approval from an OperationsManager brings the high-risk change to
        APPROVED at two votes, while the medium-risk change reaches APPROVED on one.

        PRD: "An `APPROVE` that brings the count exactly to the requirement — that is,
        where the existing `approval_count` plus one equals `required_approval_count` —
        advances the MOP `UNDER_REVIEW → APPROVED`."

        Design: Corner/calculations/mop_approval_requirement_two_for_high_one_for_medium
        """
        ctx = self._hall_with_a_high_and_a_medium_risk_change()
        submit_mop(ctx["mop_high"]["id"], USER_IDS["ELECTRICAL_CONTRACTOR"])
        submit_mop(ctx["mop_medium"]["id"], USER_IDS["ELECTRICAL_CONTRACTOR"])

        approve_mop(
            ctx["mop_high"]["id"],
            role_headers=CM,
            user_id=USER_IDS["CHANGE_MANAGER"],
        )
        approve_mop(
            ctx["mop_high"]["id"],
            role_headers=OM,
            user_id=USER_IDS["OPERATIONS_MANAGER"],
        )
        high = read_mop(ctx["mop_high"]["id"])
        assert high["status"] == "APPROVED"
        assert high["approval_count"] == 2

        approve_mop(
            ctx["mop_medium"]["id"],
            role_headers=CM,
            user_id=USER_IDS["CHANGE_MANAGER"],
        )
        medium = read_mop(ctx["mop_medium"]["id"])
        assert medium["status"] == "APPROVED", (
            "one vote is the whole requirement for a medium-risk change"
        )
        assert medium["approval_count"] == 1
        assert medium["required_approval_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop_high"]["id"], CM)
        )
        assert meta["total_count"] == 2, "both votes are on the audit trail"
        assert [row["sequence"] for row in rows] == [1, 2]

        hall = read_hall(ctx["hall_id"])
        assert hall["open_mop_count"] == 0, (
            "an APPROVED MOP occupies no window and is not an open change"
        )
        assert hall["release_posture"] == "OPEN"
