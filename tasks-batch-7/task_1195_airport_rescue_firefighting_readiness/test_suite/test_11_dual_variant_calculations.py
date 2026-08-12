"""Dual-variant calculation tests — measured vs rated basis; deployment-ready vs roster."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_aircraft,
    create_firefighter,
    create_profile,
    create_vehicle,
    get_success_data,
    record_readiness_check,
    record_training,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]


def _build_airport_cert_c_with_full_fleet_and_roster():
    """Index-C certificated airport: 2 vehicles rated 2000/500, 4 firefighters
    trained 2026-04-15. Returns dict of created entities."""
    set_clock("2026-05-01T00:00:00Z")
    create_profile("KDEMO", "C")
    create_aircraft(model_name="B737-900", length_ft=138.2,
                    avg_daily_departures=6.0, in_scheduled_service=True)
    v1 = create_vehicle("RED-1", 2000, 500)
    v2 = create_vehicle("RED-2", 2000, 500)
    record_readiness_check(v1["id"], 2000, 500, True)
    record_readiness_check(v2["id"], 2000, 500, True)
    ffs = []
    for i in range(1, 5):
        ff = create_firefighter(f"FF-{100 + i}", f"FF {i}")
        drill_type = "AIRCRAFT" if i <= 2 else "STRUCTURAL"
        record_training(ff["id"], completed_on="2026-04-15",
                        drill_type=drill_type, result="PASS")
        ffs.append(ff)
    return {"veh1": v1, "veh2": v2, "firefighters": ffs}


class TestAgentCapacityRatedVsMeasuredBasis:
    def test_measured_basis_drives_supported_index(self, api):
        """PRD §3.2: "Readiness is measured, not rated." and "The
        equipment-supported side of the profile derives from the
        measured-ready fleet. Define the eligible fleet as vehicles whose
        `status` is `IN_SERVICE` and whose `latest_readiness_result` is
        `PASS`."

        Design: Difficulty/dual_variant_calc/dv_agent_capacity_rated_vs_measured_basis
        """
        ctx = _build_airport_cert_c_with_full_fleet_and_roster()
        # Recheck at reduced quantities (500 gal / 500 lb each) at a later clock
        set_clock("2026-05-01T00:05:00Z")
        record_readiness_check(ctx["veh1"]["id"], 500, 500, True)
        record_readiness_check(ctx["veh2"]["id"], 500, 500, True)
        rd = get_success_data(api.get_readiness(AC))
        # Measured: water 1000 + min(1200, 0.5*3000)=1200 -> 2200 < 3000 (C);
        # but 1000 + min(1200, 750)=750 -> 1750 >= 1500 (B). -> supported B.
        assert rd["supported_index_by_equipment"] == "B"
        # Rated basis still uses full 4000 gal: 4000 + min(1200, 1500)=5200 >= 3000
        assert rd["rated_basis_supported_index"] == "C"

    def test_downgrade_notification_raised_on_measured_drop(self, api):
        """PRD §3.3: "If the recompute caused `effective_index` to drop from
        a value at-or-above `certificated_index` to a value strictly below
        it, and no `IndexDowngradeNotification` currently sits in `PENDING`,
        `ACKNOWLEDGED`, or `OVERDUE`, the system creates one in `PENDING`
        status..."

        Design: Difficulty/dual_variant_calc/dv_agent_capacity_rated_vs_measured_basis
        """
        ctx = _build_airport_cert_c_with_full_fleet_and_roster()
        set_clock("2026-05-01T00:05:00Z")
        record_readiness_check(ctx["veh1"]["id"], 500, 500, True)
        record_readiness_check(ctx["veh2"]["id"], 500, 500, True)
        rd = get_success_data(api.get_readiness(AC))
        assert rd["effective_index"] == "B"
        assert rd["index_compliance_status"] == "NONCOMPLIANT"
        assert rd["open_notification_id"] is not None
        data, meta = validate_paginated(
            api.list_index_downgrade_notifications(AC)
        )
        assert meta["total_count"] == 1
        n = data[0]
        assert n["cause"] == "EQUIPMENT"
        assert n["prior_index"] == "C"
        assert n["downgraded_index"] == "B"
        assert n["status"] == "PENDING"


class TestStaffingRosterVsDeploymentReadyBasis:
    def test_deployment_ready_basis_drives_staffing_index(self, api):
        """PRD §3.4: "The staffing-supported index is a separate derivation
        from the equipment side. Consider only firefighters whose `status` is
        `ACTIVE` and whose `is_training_current` is `true`."

        Design: Difficulty/dual_variant_calc/dv_staffing_roster_vs_deployment_ready_basis
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        create_aircraft(model_name="B737-900", length_ft=138.2,
                        avg_daily_departures=6.0, in_scheduled_service=True)
        v1 = create_vehicle("RED-1", 2000, 500)
        v2 = create_vehicle("RED-2", 2000, 500)
        record_readiness_check(v1["id"], 2000, 500, True)
        record_readiness_check(v2["id"], 2000, 500, True)
        # 3 firefighters current (2026-04-15), 1 lapsed (2025-03-10:
        # month diff at 2026-05-01 = 14 > 12)
        ff1 = create_firefighter("FF-101", "Ann Lee")
        ff2 = create_firefighter("FF-102", "Ben Kim")
        ff3 = create_firefighter("FF-103", "Cal Ray")
        ff4 = create_firefighter("FF-104", "Dee Fox")
        record_training(ff1["id"], completed_on="2026-04-15",
                        drill_type="AIRCRAFT", result="PASS")
        record_training(ff2["id"], completed_on="2026-04-15",
                        drill_type="AIRCRAFT", result="PASS")
        record_training(ff3["id"], completed_on="2026-04-15",
                        drill_type="STRUCTURAL", result="PASS")
        record_training(ff4["id"], completed_on="2025-03-10",
                        drill_type="AIRCRAFT", result="PASS")
        rd = get_success_data(api.get_readiness(AM))
        # Roster: 4 ACTIVE >= STAFF_REQ[D]=4
        assert rd["roster_basis_supported_index"] == "D"
        # Deployment-ready: 3 >= STAFF_REQ[C]=3 but < STAFF_REQ[D]=4
        assert rd["supported_index_by_staffing"] == "C"
        assert rd["roster_active_count"] == 4
        assert rd["deployment_ready_count"] == 3

    def test_lapsed_firefighter_not_deployable(self, api):
        """PRD §3.4: "`is_deployable` is `true` exactly when `status` is
        `ACTIVE` and `is_training_current` is `true`."

        Design: Difficulty/dual_variant_calc/dv_staffing_roster_vs_deployment_ready_basis
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        create_aircraft(model_name="B737-900", length_ft=138.2,
                        avg_daily_departures=6.0, in_scheduled_service=True)
        v1 = create_vehicle("RED-1", 2000, 500)
        v2 = create_vehicle("RED-2", 2000, 500)
        record_readiness_check(v1["id"], 2000, 500, True)
        record_readiness_check(v2["id"], 2000, 500, True)
        ff1 = create_firefighter("FF-101", "Ann Lee")
        ff2 = create_firefighter("FF-102", "Ben Kim")
        ff3 = create_firefighter("FF-103", "Cal Ray")
        ff4 = create_firefighter("FF-104", "Dee Fox")
        record_training(ff1["id"], completed_on="2026-04-15",
                        drill_type="AIRCRAFT", result="PASS")
        record_training(ff2["id"], completed_on="2026-04-15",
                        drill_type="AIRCRAFT", result="PASS")
        record_training(ff3["id"], completed_on="2026-04-15",
                        drill_type="STRUCTURAL", result="PASS")
        record_training(ff4["id"], completed_on="2025-03-10",
                        drill_type="AIRCRAFT", result="PASS")
        rd = get_success_data(api.get_readiness(AM))
        assert rd["effective_index"] == "C"
        assert rd["index_compliance_status"] == "COMPLIANT"
        f4 = get_success_data(api.get_firefighter(ff4["id"], AC))
        assert f4["is_training_current"] is False
        assert f4["is_deployable"] is False


class TestSuppressionSubstitutionCap:
    def test_substitution_cap_binds_effective_water(self, api):
        """PRD §3.2: "Dry-chemical substitution is capped: the contribution
        counted toward water is the lesser of the full water-equivalent
        (`chem_sum` times `1.2`) and one-half of `WATER_REQ[I]`. Effective
        water at index `I` is then `water_sum` plus that capped substitution."

        Design: Difficulty/combinatorial_formula/cf_suppression_substitution_cap_binds
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        create_aircraft(model_name="B737-900", length_ft=138.2,
                        avg_daily_departures=6.0, in_scheduled_service=True)
        v1 = create_vehicle("RED-1", 1000, 5000)
        v2 = create_vehicle("RED-2", 1000, 5000)
        # Measured: 400 gal / 4000 lb each (pass)
        record_readiness_check(v1["id"], 400, 4000, True)
        record_readiness_check(v2["id"], 400, 4000, True)
        ffs = []
        for i in range(1, 5):
            ff = create_firefighter(f"FF-{100 + i}", f"FF {i}")
            drill_type = "AIRCRAFT" if i <= 2 else "STRUCTURAL"
            record_training(ff["id"], completed_on="2026-04-15",
                            drill_type=drill_type, result="PASS")
            ffs.append(ff)
        rd = get_success_data(api.get_readiness(AC))
        # water_sum=800, chem_sum=8000; uncapped equiv=9600
        # For C: cap = 0.5*3000=1500; effective = 800+1500=2300 < 3000 -> C not met
        # For B: cap = 0.5*1500=750; effective = 800+750=1550 >= 1500 and 2 vehicles >= 2 -> B met
        assert rd["effective_water_gal_at_certificated_index"] == 2300
        assert rd["supported_index_by_equipment"] == "B"
        assert rd["effective_index"] == "B"

    def test_fleet_count_requirement_also_checked(self, api):
        """PRD §3.2: "For a candidate index `I`, the vehicle-count
        requirement `VEH_REQ[I]` is `1` for `A`, `2` for `B`, `2` for `C`,
        `3` for `D`, and `3` for `E`; the fleet size must be at least that
        number."

        Design: Difficulty/combinatorial_formula/cf_suppression_substitution_cap_binds
        """
        set_clock("2026-05-01T00:00:00Z")
        create_profile("KDEMO", "C")
        create_aircraft(model_name="B737-900", length_ft=138.2,
                        avg_daily_departures=6.0, in_scheduled_service=True)
        v1 = create_vehicle("RED-1", 1000, 5000)
        v2 = create_vehicle("RED-2", 1000, 5000)
        record_readiness_check(v1["id"], 400, 4000, True)
        record_readiness_check(v2["id"], 400, 4000, True)
        ffs = []
        for i in range(1, 5):
            ff = create_firefighter(f"FF-{100 + i}", f"FF {i}")
            drill_type = "AIRCRAFT" if i <= 2 else "STRUCTURAL"
            record_training(ff["id"], completed_on="2026-04-15",
                            drill_type=drill_type, result="PASS")
            ffs.append(ff)
        rd = get_success_data(api.get_readiness(AC))
        # With only 2 passing vehicles, even if effective water for C were
        # enough, the count check would block C; here both bind, supported = B.
        assert rd["in_service_passing_vehicle_count"] == 2
        assert rd["supported_index_by_equipment"] == "B"
