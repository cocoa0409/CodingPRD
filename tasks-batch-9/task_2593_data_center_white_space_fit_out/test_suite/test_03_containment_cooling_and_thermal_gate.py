"""Containment leakage, the two cooling capacity variants, and what the thermal
posture gates in commissioning."""
import pytest

from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    WA,
    approve_script,
    create_package,
    create_zone,
    execute_script,
    leakage_test,
    read_capacity_summary,
    read_cooling_unit,
    read_hall,
    read_package,
    read_rack,
    read_zone,
    remediate_zone,
    setup_commissioning_hall,
    setup_fit_out_hall,
    prove_zone_and_cooling,
    witness_package,
)


class TestCoolingCapacityVariants:
    """Nameplate capacity is blind to containment; airflow capacity is not, so a
    second leaking aisle moves one variant and not the other."""

    def _hall_with_one_proved_aisle(self):
        ctx = setup_fit_out_hall(
            "HB1",
            cu_rated_sensible_kw=120.00,
            cu_design_airflow_cfm=22000,
            cu_supply_delta_t_f=18.0,
        )
        prove_zone_and_cooling(ctx, measured_leakage_pct=5.00)
        ctx["zone_2"] = create_zone(ctx["hall_id"], "CA-2")
        return ctx

    def test_a_second_leaking_aisle_moves_only_the_airflow_variant(self):
        """A 15.00 percent leakage reading on the second aisle governs the whole room:
        the airflow variant falls from 119.08 kW to 106.54 kW while the nameplate
        variant stays at 120.00 kW.

        PRD: "Each duty unit's `airflow_capacity_kw` is its `measured_airflow_cfm`,
        multiplied by one minus the hall's leakage fraction, multiplied by its
        `supply_delta_t_f`, multiplied by the airflow coefficient 1.08, divided by 3412
        to convert BTU per hour into kilowatts, and rounded to five decimal places."

        Design: Difficulty/dual_variant_calc/cooling_capacity_nameplate_vs_airflow_divergence
        """
        ctx = self._hall_with_one_proved_aisle()
        before = read_hall(ctx["hall_id"])
        assert before["cooling_capacity_nameplate_kw"] == pytest.approx(120.00, abs=0.005)
        assert before["cooling_capacity_airflow_kw"] == pytest.approx(119.08, abs=0.005)

        failed = leakage_test(ctx["zone_2"]["id"], 15.00, 20.0)
        assert failed["leakage_status"] == "FAIL", (
            "15.00 percent measured against a 5.00 percent target fails"
        )
        assert failed["test_count"] == 1

        after = read_hall(ctx["hall_id"])
        assert after["cooling_capacity_nameplate_kw"] == pytest.approx(
            120.00, abs=0.005
        ), "the nameplate variant is blind to containment"
        assert after["cooling_capacity_airflow_kw"] == pytest.approx(106.54, abs=0.005)
        assert after["cooling_capacity_kw"] == pytest.approx(106.54, abs=0.005)
        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["worst_leakage_pct"] == pytest.approx(15.00, abs=0.005), (
            "one bad aisle governs the whole room"
        )
        unit = read_cooling_unit(ctx["cu_1"]["id"])
        assert unit["airflow_capacity_kw"] == pytest.approx(106.54396, abs=0.000005), (
            "the per-unit figure is carried at five decimal places"
        )

    def test_the_gating_variant_is_the_smaller_one_and_the_pair_diverges(self):
        """After the failing test the two published variants differ by 13.46 kW, the
        smaller one gates, and with no rack drawing load the posture stays NOMINAL.

        PRD: "`cooling_capacity_kw` is the smaller of the two variants, and
        `cooling_margin_kw` is that gating capacity less `thermal_load_kw`, rounded to
        two decimal places."

        Design: Difficulty/dual_variant_calc/cooling_capacity_nameplate_vs_airflow_divergence
        """
        ctx = self._hall_with_one_proved_aisle()
        leakage_test(ctx["zone_2"]["id"], 15.00, 20.0)

        hall = read_hall(ctx["hall_id"])
        nameplate = hall["cooling_capacity_nameplate_kw"]
        airflow = hall["cooling_capacity_airflow_kw"]
        assert nameplate - airflow == pytest.approx(13.46, abs=0.005), (
            "the same machine reads 13.46 kW lower once the leakage is counted"
        )
        assert hall["cooling_capacity_kw"] == pytest.approx(min(nameplate, airflow), abs=0.005)
        assert hall["thermal_load_kw"] == pytest.approx(0.00, abs=0.005), (
            "no rack of this hall is drawing load"
        )
        assert hall["cooling_margin_kw"] == pytest.approx(106.54, abs=0.005)
        assert hall["thermal_posture"] == "NOMINAL", (
            "a margin of 0.00 or better is NOMINAL however far the variants diverge"
        )
        assert read_zone(ctx["zone"]["id"])["leakage_status"] == "PASS", (
            "the first aisle keeps its passing verdict"
        )


class TestLeakFailureBlocksHigherLevelPackages:
    """A failing leakage test propagates zone to cooling model to package state."""

    def _commissioning_hall_with_two_packages(self):
        ctx = setup_commissioning_hall(
            "HJ1",
            cu_rated_sensible_kw=20.00,
            cu_design_airflow_cfm=3000,
            cu_supply_delta_t_f=12.0,
            rack_design_kw=12.00,
            rack_feed_kw=6.00,
        )
        ctx["pkg_l1"] = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        ctx["pkg_l4"] = create_package(ctx["hall_id"], "L4", target_load_kw=10.00)
        ctx["zone_2"] = create_zone(ctx["hall_id"], "CA-2")
        return ctx

    def test_failing_aisle_blocks_the_level_four_package_and_spares_level_one(self):
        """The leak drops the posture below NOMINAL, which moves the pending L4 package
        to BLOCKED on both its witness dimension and its projected state while the L1
        package is left untouched.

        PRD: "every commissioning package of that hall at level `L4` or `L5` whose
        `witness_status` is `PENDING` is moved to `BLOCKED`, and each such package's
        `package_state` becomes `BLOCKED` with it."

        Design: Difficulty/transitive_cascade/containment_leak_failure_blocks_level_four_packages
        """
        ctx = self._commissioning_hall_with_two_packages()
        leakage_test(ctx["zone_2"]["id"], 15.00, 20.0)

        l4 = read_package(ctx["pkg_l4"]["id"])
        assert l4["witness_status"] == "BLOCKED"
        assert l4["package_state"] == "BLOCKED"
        l1 = read_package(ctx["pkg_l1"]["id"])
        assert l1["witness_status"] == "PENDING", (
            "only levels four and five are blocked by the posture"
        )
        assert l1["package_state"] == "DRAFT"
        assert read_zone(ctx["zone"]["id"])["leakage_status"] == "PASS"
        assert read_zone(ctx["zone_2"]["id"])["leakage_status"] == "FAIL"

    def test_the_leak_drives_the_margin_negative_and_restricts_the_room(self):
        """The 15.00 percent reading takes airflow capacity below the 10.20 kW demand,
        so the margin turns negative, the posture becomes CONSTRAINED and the release
        posture becomes RESTRICTED — with no rack put at risk.

        PRD: "A negative margin no worse than 25.00 kW short — that is, a margin at or
        above negative 25.00 — yields `CONSTRAINED`."

        Design: Difficulty/transitive_cascade/containment_leak_failure_blocks_level_four_packages
        """
        ctx = self._commissioning_hall_with_two_packages()
        leakage_test(ctx["zone_2"]["id"], 15.00, 20.0)

        hall = read_hall(ctx["hall_id"])
        assert hall["cooling_capacity_nameplate_kw"] == pytest.approx(20.00, abs=0.005)
        assert hall["cooling_capacity_airflow_kw"] == pytest.approx(9.69, abs=0.005)
        assert hall["cooling_capacity_kw"] == pytest.approx(9.69, abs=0.005)
        assert hall["thermal_load_kw"] == pytest.approx(10.20, abs=0.005), (
            "12.00 kW of designed density at the diversity factor 0.85"
        )
        assert hall["cooling_margin_kw"] == pytest.approx(-0.51, abs=0.005)
        assert hall["thermal_posture"] == "CONSTRAINED"
        assert hall["release_posture"] == "RESTRICTED"
        assert hall["at_risk_rack_count"] == 0, (
            "a thermal shortfall does not put a rack at risk"
        )
        assert read_rack(ctx["rack_1"]["id"])["status"] == "POWERED"
        assert read_cooling_unit(ctx["cu_1"]["id"])[
            "airflow_capacity_kw"
        ] == pytest.approx(9.68581, abs=0.000005)


class TestWitnessRequiresNominalPosture:
    """Signing off a package is gated on the room, not just on the package."""

    def _executed_package_in_a_constrained_hall(self):
        ctx = setup_commissioning_hall(
            "HP1",
            cu_rated_sensible_kw=20.00,
            cu_design_airflow_cfm=3000,
            cu_supply_delta_t_f=12.0,
            rack_design_kw=12.00,
            rack_feed_kw=6.00,
        )
        package = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        approve_script(package["id"])
        ctx["package"] = execute_script(package["id"])
        ctx["zone_2"] = create_zone(ctx["hall_id"], "CA-2")
        leakage_test(ctx["zone_2"]["id"], 15.00, 20.0)
        return ctx

    def test_witness_is_refused_until_remediation_restores_the_posture(self):
        """A WITNESSED decision on an executed package is refused while the room is
        CONSTRAINED; dropping the failed aisle into remediation clears the measurement,
        returns the posture to NOMINAL, and the same decision then certifies.

        PRD: "Three operations require `thermal_posture` to be exactly `NOMINAL` and
        are refused with `ERR_THERMAL_POSTURE_NOT_NOMINAL` otherwise: executing a
        commissioning package's script, recording a witness decision on a package where
        that `decision` is `WITNESSED`, and starting a load bank run."

        Design: Difficulty/cross_entity_state_dependency/package_witness_requires_hall_thermal_posture_nominal
        """
        ctx = self._executed_package_in_a_constrained_hall()
        assert read_hall(ctx["hall_id"])["thermal_posture"] == "CONSTRAINED"

        validate_error(
            api_client.witness_package(
                ctx["package"]["id"], {"decision": "WITNESSED"}, WA
            ),
            ApiErrorId.ERR_THERMAL_POSTURE_NOT_NOMINAL.value,
            409,
        )
        blocked = read_package(ctx["package"]["id"])
        assert blocked["witness_status"] == "PENDING"
        assert blocked["witnessed_by_user_id"] is None
        assert blocked["script_status"] == "EXECUTED"

        remediated = remediate_zone(ctx["zone_2"]["id"])
        assert remediated["leakage_status"] == "REMEDIATION"
        assert remediated["measured_leakage_pct"] is None
        assert remediated["measured_static_pressure_pa"] is None

        hall = read_hall(ctx["hall_id"])
        assert hall["cooling_capacity_airflow_kw"] == pytest.approx(10.83, abs=0.005)
        assert hall["cooling_margin_kw"] == pytest.approx(0.63, abs=0.005)
        assert hall["thermal_posture"] == "NOMINAL"

        certified = validate_success(
            api_client.witness_package(
                ctx["package"]["id"], {"decision": "WITNESSED"}, WA
            ),
            200,
        )
        assert certified["witness_status"] == "WITNESSED"
        assert certified["package_state"] == "CERTIFIED"
        assert certified["witnessed_by_user_id"] == "u-wa-1"

    def test_remediation_keeps_the_test_history_and_leaves_the_hall_commissioning(self):
        """Remediation drops the aisle out of the worst-leakage selection without
        erasing that a test was run, and certifying one L1 package does not take the
        hall live.

        PRD: "which deliberately drops the zone out of the hall's worst-leakage
        selection while the crew is working on it."

        Design: Difficulty/cross_entity_state_dependency/package_witness_requires_hall_thermal_posture_nominal
        """
        ctx = self._executed_package_in_a_constrained_hall()
        remediate_zone(ctx["zone_2"]["id"])

        zone_2 = read_zone(ctx["zone_2"]["id"])
        assert zone_2["test_count"] == 1, "the remediated zone keeps its test history"
        summary = read_capacity_summary(ctx["hall_id"])
        assert summary["worst_leakage_pct"] == pytest.approx(5.00, abs=0.005), (
            "only the passing aisle still carries a measurement"
        )

        witness_package(ctx["package"]["id"], "WITNESSED")
        after = read_hall(ctx["hall_id"])
        assert after["status"] == "COMMISSIONING", (
            "a hall with a single certified L1 package does not go live"
        )
        assert after["release_posture"] == "OPEN"
