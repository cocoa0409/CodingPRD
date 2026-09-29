"""Declared state transitions across the white space: initial states, the phase
ladder, the transitions no operator may request twice, and the side effects each
accepted transition is obliged to produce.
"""
import pytest

from test_helpers import (
    api_client,
    assert_cage,
    assert_containment_zone,
    assert_cooling_unit,
    assert_hall,
    assert_pdu,
    assert_rack,
    assert_security_device,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    EC,
    FP,
    MC,
    SA,
    add_powered_rack,
    advance_phase,
    commission_device,
    commission_pdu,
    create_busway,
    create_cage,
    create_camera,
    create_hall,
    create_pdu,
    create_rack,
    create_tenant,
    create_zone,
    install_rack,
    leakage_test,
    prove_zone_and_cooling,
    read_busway,
    read_cage,
    read_cooling_unit,
    read_device,
    read_feed,
    read_hall,
    read_pdu,
    read_rack,
    read_zone,
    setup_fit_out_hall,
)


class TestHallPhaseLadder:
    """A hall opens in PLANNING and is walked one phase at a time; the last step
    is never requested by an operator."""

    def _skeleton_hall(self, code: str, name: str, *, with_b_side: bool = True):
        """Hall plus the electrical and mechanical skeleton the first phase
        advance asks for, with the B-side unit optionally withheld."""
        hall = create_hall(
            code,
            name=name,
            tenant_mode="SINGLE_TENANT",
            design_kw_capacity=400.00,
            gross_area_sqm=600.0,
            cooling_redundancy="N",
            planned_rack_count=8,
        )
        pdu_a = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        if with_b_side:
            create_pdu(hall["id"], "PDU-B1", "B", rated_kw=300.00)
        create_busway(
            pdu_a["id"],
            "BW-A1",
            rated_amps=400,
            voltage_v=415,
            redundancy_topology="N_PLUS_1",
        )
        create_zone(
            hall["id"],
            "CA-1",
            zone_type="COLD_AISLE",
            containment_kind="RIGID_ROOF",
            target_leakage_pct=5.00,
            design_static_pressure_pa=20.0,
        )
        return hall

    def test_new_hall_opens_in_planning(self):
        """A freshly registered white space reports the initial phase of the
        ladder, and the status filter on the hall list finds it there.

        PRD §3.1: "The hall is born in `PLANNING`."
        PRD §3.1: "Hall and tenant lists may be narrowed by `status`,
        `tenant_mode` and `code` respectively."

        Design: Corner/state_machines/hall_initial_state_is_planning
        """
        created = validate_success(
            api_client.create_hall(
                {
                    "name": "Corner Hall 20",
                    "code": "CX20",
                    "tenant_mode": "SINGLE_TENANT",
                    "design_kw_capacity": 400.00,
                    "gross_area_sqm": 600.0,
                    "cooling_redundancy": "N",
                    "planned_rack_count": 8,
                },
                FP,
            ),
            201,
        )
        assert created["status"] == "PLANNING", "a new white space opens in PLANNING"
        assert_hall(created)
        assert read_hall(created["id"])["status"] == "PLANNING"

        rows, meta = validate_paginated(
            api_client.list_halls(FP, {"status": "PLANNING"})
        )
        assert meta["total_count"] == 1, "the only hall in the room list is PLANNING"
        assert [row["code"] for row in rows] == ["CX20"]

    def test_advance_phase_to_non_successor_is_rejected(self):
        """Naming COMMISSIONING from PLANNING is refused even though every
        prerequisite of the intermediate step is already satisfied, and the hall
        is left where it stood.

        PRD §3.1: "Only the immediate successor of the hall's current phase is
        accepted, and `LIVE` is never accepted from this capability at all; naming
        a non-successor, naming a phase the hall has already passed, or naming
        `LIVE` is rejected with `ERR_HALL_PHASE_INVALID`."

        Design: Corner/state_machines/hall_advance_phase_to_non_successor_rejected
        """
        hall = self._skeleton_hall("CX21", "Corner Hall 21")

        validate_error(
            api_client.advance_hall_phase(
                hall["id"], {"target_status": "COMMISSIONING"}, FP
            ),
            ApiErrorId.ERR_HALL_PHASE_INVALID.value,
            409,
        )
        after = read_hall(hall["id"])
        assert after["status"] == "PLANNING", "the refused advance moved no phase"
        assert_hall(after)

    def test_advance_phase_never_accepts_live(self):
        """LIVE is reachable only through the system transition fired by a witness
        decision, so an operator naming it on the phase capability is refused and
        the hall stays in FIT_OUT.

        PRD §3.1: "A hall walks `PLANNING → FIT_OUT → COMMISSIONING → LIVE`, and
        `LIVE` is terminal."
        PRD §3.1: "Only the immediate successor of the hall's current phase is
        accepted, and `LIVE` is never accepted from this capability at all; naming
        a non-successor, naming a phase the hall has already passed, or naming
        `LIVE` is rejected with `ERR_HALL_PHASE_INVALID`."

        Design: Corner/state_machines/hall_advance_phase_to_live_is_never_accepted
        """
        hall = self._skeleton_hall("CX22", "Corner Hall 22")
        advanced = advance_phase(hall["id"], "FIT_OUT")
        assert advanced["status"] == "FIT_OUT"

        validate_error(
            api_client.advance_hall_phase(hall["id"], {"target_status": "LIVE"}, FP),
            ApiErrorId.ERR_HALL_PHASE_INVALID.value,
            409,
        )
        after = read_hall(hall["id"])
        assert after["status"] == "FIT_OUT", "no operator may hand a hall over"
        assert_hall(after)

    def test_advance_phase_without_b_side_unit_is_rejected(self):
        """A hall holding only the A-side unit — with its busway and containment
        zone in place — fails the redundant-feed-path prerequisite rather than the
        successor check, and stays in PLANNING.

        PRD §3.1: "Advancing `PLANNING → FIT_OUT` demands that the electrical and
        mechanical skeletons exist: the hall must have at least one power
        distribution unit on `feed_side` `A` **and** at least one on `feed_side`
        `B` (redundant feed paths are not optional), at least one busway run, and
        at least one containment zone."
        PRD §3.1: "Any of those missing is rejected with
        `ERR_PHASE_PREREQ_NOT_MET`."

        Design: Corner/state_machines/hall_phase_prereq_missing_b_side_pdu_rejected
        """
        hall = self._skeleton_hall("CX23", "Corner Hall 23", with_b_side=False)

        validate_error(
            api_client.advance_hall_phase(hall["id"], {"target_status": "FIT_OUT"}, FP),
            ApiErrorId.ERR_PHASE_PREREQ_NOT_MET.value,
            409,
        )
        after = read_hall(hall["id"])
        assert after["status"] == "PLANNING", "the missing B-side unit blocks the ladder"
        assert_hall(after)


class TestPowerDistributionUnitCommissioning:
    """Recording a measured derate is the unit's only transition, and it re-runs
    the ceiling of every busway beneath it."""

    def _hall_with_unit_and_run(self, code: str, name: str):
        hall = create_hall(
            code,
            name=name,
            tenant_mode="SINGLE_TENANT",
            design_kw_capacity=400.00,
            gross_area_sqm=600.0,
            cooling_redundancy="N",
            planned_rack_count=8,
        )
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        busway = create_busway(
            pdu["id"],
            "BW-A1",
            rated_amps=400,
            voltage_v=415,
            redundancy_topology="N_PLUS_1",
        )
        return hall, pdu, busway

    def test_recording_the_derate_commissions_the_unit_and_leaves_design_ceiling(self):
        """The write stores 0.94, moves the unit to COMMISSIONED and re-runs the
        ceiling of BW-A1 — which, under the DESIGN variant the run recorded in a
        PLANNING hall, ignores the derate and stays at 196.66 kW.

        PRD §3.2: "On success the factor is stored, the unit's status becomes
        `COMMISSIONED`, and every busway beneath it recomputes its own `usable_kw`
        under whichever variant that busway currently sits in — which means a
        measured derate below 1.00 lowers the commissioned ceiling immediately
        while leaving the design ceiling untouched."
        PRD §3.2: "The `DESIGN` variant ignores the measured derate entirely, so
        design-time reservations are checked against a nameplate-derived ceiling"
        PRD §3.2: "A new unit sits at `PLANNED`, its `measured_derate_factor`
        defaults to 1.00, and its `usable_cap_kw` is set immediately to the
        nameplate rating multiplied by the continuous-load factor of 0.80, rounded
        to three decimal places."

        Design: Corner/state_machines/pdu_patch_commissions_and_recomputes_busway_under_design_variant
        """
        hall, pdu, busway = self._hall_with_unit_and_run("CX24", "Corner Hall 24")
        assert busway["usable_variant"] == "DESIGN"

        commissioned = validate_success(
            api_client.patch_pdu(pdu["id"], {"measured_derate_factor": 0.94}, EC), 200
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["measured_derate_factor"] == pytest.approx(0.94, abs=0.005)
        assert commissioned["usable_cap_kw"] == pytest.approx(240.000, abs=0.0005), (
            "the 300.00 kW nameplate at the continuous-load factor 0.80"
        )
        assert_pdu(commissioned)

        after = read_busway(busway["id"])
        assert after["usable_variant"] == "DESIGN", (
            "a run created while its hall is in PLANNING keeps the DESIGN variant"
        )
        assert after["usable_kw"] == pytest.approx(196.66, abs=0.005), (
            "the DESIGN variant ignores the measured derate entirely"
        )
        assert after["raw_kw"] == pytest.approx(273.136, abs=0.0005)
        assert read_hall(hall["id"])["status"] == "PLANNING"

    def test_second_derate_record_on_a_commissioned_unit_is_rejected(self):
        """PLANNED -> COMMISSIONED is the unit's only transition, so the retry is
        refused on the declared from-state and the stored 0.94 survives the 0.80
        the retry carried.

        PRD §3.2: "Acceptance testing eventually produces a real measurement, and
        recording it is what moves a unit `PLANNED → COMMISSIONED`."
        PRD §2.10: "**Declared from-state (`ERR_INVALID_STATE`, 409)** — the
        addressed row sits in a state from which the requested transition is
        declared."

        Design: Corner/state_machines/pdu_second_patch_from_commissioned_rejected
        """
        hall = create_hall(
            "CX25",
            name="Corner Hall 25",
            design_kw_capacity=400.00,
            gross_area_sqm=600.0,
            planned_rack_count=8,
        )
        pdu = create_pdu(hall["id"], "PDU-A1", "A", rated_kw=300.00)
        commission_pdu(pdu["id"], 0.94)

        validate_error(
            api_client.patch_pdu(pdu["id"], {"measured_derate_factor": 0.80}, EC),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_pdu(pdu["id"])
        assert after["status"] == "COMMISSIONED"
        assert after["measured_derate_factor"] == pytest.approx(0.94, abs=0.005), (
            "the refused retry did not overwrite the recorded measurement"
        )
        assert after["usable_cap_kw"] == pytest.approx(240.000, abs=0.0005)


class TestBuswayEnergisation:
    """Energisation is declared only from INSTALLED, so the repeat is an error
    rather than a silent no-op."""

    def test_second_energize_of_an_energized_run_is_rejected(self):
        """The first energise returns the run at ENERGIZED with its ceiling
        recomputed; the immediate repeat is refused and the run stays energised.

        PRD §3.2: "Energising a run advances it `INSTALLED → ENERGIZED`."
        PRD §3.2: "and the run must actually be sitting at `INSTALLED` —
        attempting it on a run that is already `ENERGIZED` or that has been driven
        `ISOLATED` is refused with `ERR_INVALID_STATE`."
        PRD §3.2: "On success the run's status becomes `ENERGIZED` and its
        `usable_kw` is recomputed under the variant the hall's current phase
        selects."

        Design: Corner/state_machines/busway_energize_then_second_energize_rejected
        """
        ctx = setup_fit_out_hall("CX26", energize=False)
        assert read_busway(ctx["bw_a"]["id"])["status"] == "INSTALLED"

        energised = validate_success(
            api_client.energize_busway(ctx["bw_a"]["id"], EC), 200
        )
        assert energised["status"] == "ENERGIZED"

        validate_error(
            api_client.energize_busway(ctx["bw_a"]["id"], EC),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_busway(ctx["bw_a"]["id"])
        assert after["status"] == "ENERGIZED", "the refused repeat left the run alone"
        assert after["usable_kw"] == pytest.approx(196.66, abs=0.005)
        assert after["usable_variant"] == "DESIGN", (
            "a FIT_OUT hall selects the design-time ceiling"
        )
        assert after["committed_kw"] == pytest.approx(0.000, abs=0.0005)
        assert after["feed_count"] == 0


class TestContainmentZoneProvingCycle:
    """A zone walks UNTESTED, FAIL, REMEDIATION and PASS under one conjunction,
    and neither a passed result nor an untested one may be short-circuited."""

    def _hall_with_zone(self, code: str, name: str, *, zone_type: str = "COLD_AISLE",
                        containment_kind: str = "RIGID_ROOF"):
        hall = create_hall(
            code,
            name=name,
            tenant_mode="SINGLE_TENANT",
            design_kw_capacity=400.00,
            gross_area_sqm=600.0,
            cooling_redundancy="N",
            planned_rack_count=8,
        )
        zone = create_zone(
            hall["id"],
            "CA-1",
            zone_type=zone_type,
            containment_kind=containment_kind,
            target_leakage_pct=5.00,
            design_static_pressure_pa=20.0,
        )
        return hall, zone

    def test_zone_cycles_fail_then_remediation_then_pass(self):
        """The failing test stores 8.00 % and counts, remediation clears both
        measurements without unwinding the count, and the re-test from REMEDIATION
        passes at 4.00 % with the count at 2.

        PRD §3.5: "The verdict is a conjunction of two conditions: measured leakage
        must be no greater than the zone's `target_leakage_pct`, **and** measured
        static pressure must be at least ninety percent of the design pressure —
        specifically, at least the design pressure multiplied by 0.90 and rounded to
        two decimal places."
        PRD §3.5: "Whichever the verdict, both measured values are stored and
        `test_count` grows by one."
        PRD §3.5: "Putting a failed zone into `REMEDIATION` optionally records a
        `remediation_note`, sets `leakage_status` to `REMEDIATION`, and clears both
        `measured_leakage_pct` and `measured_static_pressure_pa` back to null"
        PRD §3.5: "Testing again from `REMEDIATION` lands on `PASS` or `FAIL` under
        exactly the same two conditions and with exactly the same side effects as a
        first test"

        Design: Corner/state_machines/containment_zone_fail_remediate_pass_cycle
        """
        hall, zone = self._hall_with_zone("CX27", "Corner Hall 27", zone_type="HOT_AISLE")
        assert zone["leakage_status"] == "UNTESTED"
        assert zone["test_count"] == 0

        failed = validate_success(
            api_client.leakage_test(
                zone["id"],
                {"measured_leakage_pct": 8.00, "measured_static_pressure_pa": 20.0},
                MC,
            ),
            200,
        )
        assert failed["leakage_status"] == "FAIL", "8.00 % breaches the 5.00 % target"
        assert failed["measured_leakage_pct"] == pytest.approx(8.00, abs=0.005)
        assert failed["test_count"] == 1
        assert_containment_zone(failed)

        remediated = validate_success(
            api_client.remediate_zone(
                zone["id"], {"remediation_note": "Re-sealed roof panels 4-7."}, MC
            ),
            200,
        )
        assert remediated["leakage_status"] == "REMEDIATION"
        assert remediated["measured_leakage_pct"] is None, (
            "remediation drops the zone out of the worst-leakage selection"
        )
        assert remediated["measured_static_pressure_pa"] is None
        assert remediated["test_count"] == 1, "remediation does not unwind the count"

        passed = validate_success(
            api_client.leakage_test(
                zone["id"],
                {"measured_leakage_pct": 4.00, "measured_static_pressure_pa": 20.0},
                MC,
            ),
            200,
        )
        assert passed["leakage_status"] == "PASS"
        assert passed["measured_leakage_pct"] == pytest.approx(4.00, abs=0.005)
        assert passed["test_count"] == 2

        after = read_hall(hall["id"])
        assert after["thermal_posture"] == "NOMINAL", (
            "with no duty unit and no powered rack the margin stays at 0.00"
        )
        assert after["cooling_margin_kw"] == pytest.approx(0.00, abs=0.005)

    def test_leakage_test_on_a_passed_zone_is_rejected(self):
        """A zone measured at exactly its target passes, and the follow-up test is
        refused so a passed containment result cannot be quietly overwritten.

        PRD §3.5: "A zone that already stands at `PASS` is never re-tested: the
        request is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/containment_zone_leakage_test_from_pass_rejected
        """
        hall, zone = self._hall_with_zone("CX28", "Corner Hall 28")
        passed = leakage_test(zone["id"], 5.00, 20.0)
        assert passed["leakage_status"] == "PASS", "5.00 % meets a 5.00 % target"

        validate_error(
            api_client.leakage_test(
                zone["id"],
                {"measured_leakage_pct": 3.00, "measured_static_pressure_pa": 20.0},
                MC,
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_zone(zone["id"])
        assert after["leakage_status"] == "PASS"
        assert after["measured_leakage_pct"] == pytest.approx(5.00, abs=0.005), (
            "the refused re-test overwrote no measurement"
        )
        assert after["test_count"] == 1

    def test_remediating_an_untested_zone_is_rejected(self):
        """Remediation cannot be used to skip the first leakage test: an UNTESTED
        zone refuses it and keeps its untested count.

        PRD §3.5: "A zone at `FAIL` cannot be re-tested either until it has been
        through remediation, and remediation may only be entered from `FAIL` —
        attempting it from `UNTESTED`, `PASS` or `REMEDIATION` is likewise
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/containment_zone_remediate_from_untested_rejected
        """
        hall, zone = self._hall_with_zone(
            "CX29", "Corner Hall 29", containment_kind="CURTAIN"
        )
        assert zone["leakage_status"] == "UNTESTED"

        validate_error(
            api_client.remediate_zone(
                zone["id"], {"remediation_note": "Pre-emptive re-seal."}, MC
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_zone(zone["id"])
        assert after["leakage_status"] == "UNTESTED"
        assert after["test_count"] == 0
        assert after["measured_leakage_pct"] is None

    def test_static_pressure_floor_decides_the_verdict_at_the_boundary(self):
        """At 1.00 % leakage — comfortably inside the 5.00 % target — 17.9 Pa still
        FAILs against the 18.00 Pa floor of a 20.0 Pa design, and exactly 18.0 Pa
        PASSes on the same leakage after remediation.

        PRD §3.5: "The verdict is a conjunction of two conditions: measured leakage
        must be no greater than the zone's `target_leakage_pct`, **and** measured
        static pressure must be at least ninety percent of the design pressure —
        specifically, at least the design pressure multiplied by 0.90 and rounded to
        two decimal places."
        PRD §3.5: "Both satisfied means `PASS`; either violated means `FAIL`."

        Design: Corner/state_machines/containment_zone_static_pressure_floor_boundary_enforced
        """
        hall, zone = self._hall_with_zone("CX30", "Corner Hall 30")

        below = validate_success(
            api_client.leakage_test(
                zone["id"],
                {"measured_leakage_pct": 1.00, "measured_static_pressure_pa": 17.9},
                MC,
            ),
            200,
        )
        assert below["leakage_status"] == "FAIL", (
            "17.9 Pa sits below the 18.00 Pa floor even at 1.00 % leakage"
        )
        assert below["measured_leakage_pct"] == pytest.approx(1.00, abs=0.005)
        assert below["test_count"] == 1

        validate_success(
            api_client.remediate_zone(
                zone["id"], {"remediation_note": "Rebalanced supply fans."}, MC
            ),
            200,
        )

        at_floor = validate_success(
            api_client.leakage_test(
                zone["id"],
                {"measured_leakage_pct": 1.00, "measured_static_pressure_pa": 18.0},
                MC,
            ),
            200,
        )
        assert at_floor["leakage_status"] == "PASS", (
            "exactly ninety percent of the design pressure satisfies the floor"
        )
        assert at_floor["measured_static_pressure_pa"] == pytest.approx(18.0, abs=0.05)
        assert at_floor["test_count"] == 2


class TestCoolingUnitDutyEntry:
    """A unit enters the duty set only after a recorded airflow measurement, and
    only the second transition admits it to the hall's capacity variants."""

    def test_place_in_service_from_installed_is_rejected(self):
        """An INSTALLED unit with no recorded airflow refuses duty entry, so the
        hall's cooling capacity stays where creation seeded it.

        PRD §3.5: "A unit still at `INSTALLED` cannot be placed in service, and the
        attempt is refused with `ERR_INVALID_STATE`."
        PRD §3.5: "A new unit stands at `INSTALLED` with `measured_airflow_cfm` null
        and `airflow_capacity_kw` at 0.00."

        Design: Corner/state_machines/cooling_unit_place_in_service_from_installed_rejected
        """
        ctx = setup_fit_out_hall("CX31", energize=False, cu_rated_sensible_kw=120.00)
        unit = ctx["cu_1"]
        assert unit["status"] == "INSTALLED"

        validate_error(
            api_client.place_cooling_unit_in_service(unit["id"], MC),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_cooling_unit(unit["id"])
        assert after["status"] == "INSTALLED", "duty entry needs a measurement first"
        assert after["measured_airflow_cfm"] is None
        assert_cooling_unit(after)

        hall = read_hall(ctx["hall_id"])
        assert hall["cooling_capacity_kw"] == pytest.approx(0.00, abs=0.005), (
            "an uncommissioned unit contributes to neither capacity variant"
        )

    def test_commission_then_place_in_service_side_effects(self):
        """Commissioning stores 22000 cfm and computes the unit's own airflow
        capacity at five decimal places while the hall's two variants stay at 0.00;
        only duty entry lifts them to 120.00 and 119.08 kW.

        PRD §3.5: "Commissioning a unit records `measured_airflow_cfm` and advances
        it `INSTALLED → COMMISSIONED`."
        PRD §3.5: "On success the measurement is stored and the unit's
        `airflow_capacity_kw` is computed for the first time."
        PRD §3.5: "Placing a commissioned unit into duty advances it `COMMISSIONED →
        IN_SERVICE` and re-derives the hall cooling model, because only now does the
        unit contribute to either capacity variant."
        PRD §3.5: "The duty set is every cooling unit of the hall whose status is
        `IN_SERVICE`; units at `MAINTENANCE`, `COMMISSIONED` or `INSTALLED` are
        excluded."
        PRD §3.5: "Each duty unit's `airflow_capacity_kw` is its
        `measured_airflow_cfm`, multiplied by one minus the hall's leakage fraction,
        multiplied by its `supply_delta_t_f`, multiplied by the airflow coefficient
        1.08, divided by 3412 to convert BTU per hour into kilowatts, and rounded to
        five decimal places."

        Design: Corner/state_machines/cooling_unit_commission_then_place_in_service_side_effects
        """
        ctx = setup_fit_out_hall(
            "CX32",
            energize=False,
            cu_rated_sensible_kw=120.00,
            cu_design_airflow_cfm=22000,
            cu_supply_delta_t_f=18.0,
        )
        proved = leakage_test(ctx["zone_id"], 5.00, 20.0)
        assert proved["leakage_status"] == "PASS", "a 5.00 % leakage fraction is selected"

        commissioned = validate_success(
            api_client.commission_cooling_unit(
                ctx["cu_1"]["id"], {"measured_airflow_cfm": 22000}, MC
            ),
            200,
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert commissioned["measured_airflow_cfm"] == 22000
        assert commissioned["airflow_capacity_kw"] == pytest.approx(
            119.07855, abs=0.000005
        ), "22000 cfm at 5 % leakage and a 18.0 F delta-T"

        mid = read_hall(ctx["hall_id"])
        assert mid["cooling_capacity_nameplate_kw"] == pytest.approx(0.00, abs=0.005), (
            "a COMMISSIONED unit is not yet in the duty set"
        )
        assert mid["cooling_capacity_airflow_kw"] == pytest.approx(0.00, abs=0.005)

        in_service = validate_success(
            api_client.place_cooling_unit_in_service(ctx["cu_1"]["id"], MC), 200
        )
        assert in_service["status"] == "IN_SERVICE"

        hall = read_hall(ctx["hall_id"])
        assert hall["cooling_capacity_nameplate_kw"] == pytest.approx(120.00, abs=0.005)
        assert hall["cooling_capacity_airflow_kw"] == pytest.approx(119.08, abs=0.005)
        assert hall["cooling_capacity_kw"] == pytest.approx(119.08, abs=0.005), (
            "the airflow variant is the smaller of the two and therefore binds"
        )
        assert hall["thermal_load_kw"] == pytest.approx(0.00, abs=0.005)
        assert hall["cooling_margin_kw"] == pytest.approx(119.08, abs=0.005)
        assert hall["thermal_posture"] == "NOMINAL"
        assert_hall(hall)


class TestRackAndFeedTransitions:
    """Installation is declared only from PLANNED, and a branch feed may only be
    handed back while its rack is still out of service."""

    def test_installing_a_rack_twice_is_rejected(self):
        """The second installation of the same position is refused, its as-built tag
        is not overwritten by the retry, and the hall counts the position once.

        PRD §3.4: "**Installation** advances a position `PLANNED → INSTALLED` and is
        the moment the position starts costing a tenant something."
        PRD §2.10: "**Declared from-state (`ERR_INVALID_STATE`, 409)** — the
        addressed row sits in a state from which the requested transition is
        declared."
        PRD §3.4: "`custody_fitout_count` counts those at `PLANNED`, `INSTALLED` or
        `AT_RISK` — the positions still in fit-out custody."
        PRD §3.4: "The hall's `chargeable_kw` is the sum of the per-rack figures over
        every rack of the hall whose status is `INSTALLED`, `POWERED`, `AT_RISK` or
        `RELEASED`, rounded again to two decimal places (a no-op when every term is
        already at two places)."

        Design: Corner/state_machines/rack_install_twice_rejected
        """
        ctx = setup_fit_out_hall("CX33", energize=False)
        rack = create_rack(ctx["hall_id"], ctx["zone_id"], "1", 1, design_kw=10.00)
        installed = install_rack(rack["id"], "AT-0001")
        assert installed["status"] == "INSTALLED"

        validate_error(
            api_client.install_rack(rack["id"], {"asset_tag": "AT-9999"}, FP),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_rack(rack["id"])
        assert after["status"] == "INSTALLED"
        assert after["asset_tag"] == "AT-0001", (
            "the refused retry wrote neither status nor as-built tag"
        )
        assert_rack(after)

        hall = read_hall(ctx["hall_id"])
        assert hall["rack_total_count"] == 1
        assert hall["custody_fitout_count"] == 1, (
            "the position is counted once on the fit-out side of the partition"
        )
        assert hall["custody_ops_count"] == 0
        assert hall["chargeable_kw"] == pytest.approx(10.45, abs=0.005), (
            "10.00 kW of designed density at the rack overhead factor 1.045"
        )
        assert_hall(hall)

    def test_releasing_an_energized_feed_under_a_powered_rack_is_rejected(self):
        """Once the rack is POWERED and its feeds ENERGIZED the soft delete is
        refused, so a live branch circuit cannot be handed back out from under a
        running cabinet and the ledger does not move.

        PRD §3.3: "**Releasing a feed** is a soft delete. It is permitted only from
        `RESERVED`, and only while the owning rack is still at `PLANNED` or
        `INSTALLED`; a feed under a powered, at-risk or released rack may not be
        given back, and the attempt is refused with `ERR_INVALID_STATE`."
        PRD §3.3: "`RESERVED → ENERGIZED` happens when the owning rack is powered
        on, and requires that the feed's run be `ENERGIZED` at that moment; the
        rack's `energized_feed_count` is re-derived."

        Design: Corner/state_machines/rack_feed_delete_of_energized_feed_rejected
        """
        ctx = setup_fit_out_hall("CX34", cu_rated_sensible_kw=200.00)
        prove_zone_and_cooling(ctx)
        add_powered_rack(
            ctx,
            grid_row="1",
            grid_col=1,
            design_kw=15.00,
            feed_kw=7.50,
            breaker_amps=32,
            asset_tag="AT-0001",
        )
        assert ctx["rack_1"]["status"] == "POWERED"
        feed_a = ctx["rack_1_feed_a"]
        assert read_feed(feed_a["id"])["status"] == "ENERGIZED"

        validate_error(
            api_client.delete_rack_feed(feed_a["id"], EC),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after = read_feed(feed_a["id"])
        assert after["status"] == "ENERGIZED", "the live feed was not soft-deleted"
        assert after["released_at"] is None
        assert after["allocated_kw"] == pytest.approx(7.500, abs=0.0005)

        busway = read_busway(ctx["bw_a"]["id"])
        assert busway["committed_kw"] == pytest.approx(7.500, abs=0.0005)
        assert busway["feed_count"] == 1, "the refused release freed no slice"

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(15.00, abs=0.005), (
            "the two 7.50 kW feeds still stand against the room"
        )
        assert hall["custody_ops_count"] == 1
        assert_hall(hall)


class TestSecurityDeviceCommissioning:
    """PLANNED to ACTIVE is a device's only transition, and the coverage it feeds
    must not be counted twice."""

    def test_second_commission_of_an_active_camera_is_rejected(self):
        """Re-commissioning an ACTIVE camera is refused, so the cage's coverage
        stays at the 75.00 % that one 30.0 m field of view over a 40.0 m perimeter
        earns and the cage remains in fit-out.

        PRD §3.6: "Commissioning a device advances it `PLANNED → ACTIVE`; attempting
        it on a device that is already `ACTIVE` is refused with `ERR_INVALID_STATE`."
        PRD §3.6: "otherwise it is the sum of `covered_length_m` across the cage's
        `ACTIVE` cameras, divided by the cage's `perimeter_length_m`, multiplied by
        100, capped at 100.00 so that overlapping camera fields cannot report more
        than full coverage, and rounded to two decimal places."
        PRD §3.6: "`active_reader_zone_count` is the number of **distinct**
        `reader_zone_label` values among the cage's `ACTIVE` card readers — two
        readers arming the same zone count once."
        PRD §3.6: "When the re-derived coverage reaches or exceeds
        `required_camera_coverage_pct` and the re-derived distinct reader-zone count
        reaches or exceeds `required_reader_zone_count`, and the cage is still at
        `FIT_OUT`, the cage advances `FIT_OUT → SECURED` in that same request."

        Design: Corner/state_machines/security_device_second_commission_rejected
        """
        hall = create_hall(
            "CX35",
            name="Corner Hall 35",
            tenant_mode="MULTI_TENANT",
            design_kw_capacity=400.00,
            gross_area_sqm=600.0,
            cooling_redundancy="N",
            planned_rack_count=8,
        )
        tenant = create_tenant(
            "CXT35",
            name="Meridian Cloud",
            contracted_kw=100.00,
            contract_start_date="2026-01-01T00:00:00Z",
        )
        cage = create_cage(
            hall["id"], tenant["id"], "CG-1", perimeter_length_m=40.0
        )
        camera = create_camera(cage["id"], "CAM-1", 30.0)
        active = commission_device(camera["id"])
        assert active["status"] == "ACTIVE"

        validate_error(
            api_client.commission_security_device(camera["id"], SA),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        after_device = read_device(camera["id"])
        assert after_device["status"] == "ACTIVE"
        assert_security_device(after_device)

        after_cage = read_cage(cage["id"])
        assert after_cage["camera_coverage_pct"] == pytest.approx(75.00, abs=0.005), (
            "30.0 m of a 40.0 m perimeter is counted once, not twice"
        )
        assert after_cage["active_reader_zone_count"] == 0, (
            "no card reader has been commissioned on this cage"
        )
        assert after_cage["operational_status"] == "FIT_OUT", (
            "75.00 % falls short of the default 95.00 % camera requirement"
        )
        assert_cage(after_cage)
