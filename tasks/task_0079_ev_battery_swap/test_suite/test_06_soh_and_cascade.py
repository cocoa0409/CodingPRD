"""SOH assessment, grade tagging, cascade grading, and recycle pathway.

Covers PRD §3.5 (SOH math + grading + cascade) and the explicit
cascade endpoints.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    create_battery,
    create_battery_model,
    drive_battery_to_charging,
    finish_charge,
    make_admin_headers,
    make_operator_headers,
    set_battery_cycle_count_via_finishes,
    setup_basic_scene,
    validate_error,
    validate_success,
)


class TestSohAssessmentMath:
    def test_clean_inputs_yield_full_soh(self, api):
        """PRD §3.5: "The capacity factor is the ratio of capacity_test_kwh
        to the battery model's rated_capacity_kwh, multiplied by one
        hundred to express it as a percentage."

        Claim: capacity_test_kwh equal to rated (50 kWh), resistance at
        baseline (50 mohm), temperature in window (25 C), cycle below
        baseline (0) → soh_pct == 100.00 (no penalties).
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert float(b2["soh_pct"]) == 100.00
        assert b2["soh_grade"] == "A"
        assert b2["status"] == "IDLE"  # grade A means not retired

    def test_resistance_penalty(self, api):
        """PRD §3.5: "The resistance penalty is zero unless
        internal_resistance_mohm strictly exceeds fifty milliohms; if it
        does, the excess milliohms above fifty are multiplied by 0.10
        percentage points per milliohm."

        Claim: internal_resistance_mohm=70 (20 over baseline 50) →
        penalty = 2.0 pct; soh_pct = 100 - 2 = 98.00.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=70.0, avg_temperature_c=25.0,
        )
        assert float(b2["soh_pct"]) == pytest.approx(98.00, abs=0.001)

    def test_temperature_penalty_high(self, api):
        """PRD §3.5: "if the average is strictly above thirty-five, the
        excess degrees above thirty-five are multiplied by 0.05 percentage
        points per degree".

        Claim: avg_temperature_c=45 (10 over 35) → penalty = 0.5 pct;
        soh_pct = 100 - 0.5 = 99.50.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=50.0, avg_temperature_c=45.0,
        )
        assert float(b2["soh_pct"]) == pytest.approx(99.50, abs=0.001)

    def test_temperature_penalty_low(self, api):
        """PRD §3.5: "if the average is strictly below ten, the shortfall
        in degrees below ten is multiplied by the same 0.05 per degree."

        Claim: avg_temperature_c=0 (10 below 10) → penalty = 0.5 pct;
        soh_pct = 100 - 0.5 = 99.50.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=50.0, avg_temperature_c=0.0,
        )
        assert float(b2["soh_pct"]) == pytest.approx(99.50, abs=0.001)


class TestGradeBoundary:
    def test_grade_a_at_exactly_90(self, api):
        """PRD §3.5: "A value of at least 90.0 grades the battery `A`".

        Claim: capacity_test_kwh=45 over rated 50 (capacity factor 90,
        no penalties) → soh_pct=90.00 and grade=A.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=45.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert float(b2["soh_pct"]) == pytest.approx(90.00, abs=0.001)
        assert b2["soh_grade"] == "A"

    def test_grade_b_at_exactly_floor(self, api):
        """PRD §3.5: "exactly `ev_soh_floor_pct` is `B`, not `C`, and
        exactly 70.0 is `C`, not `RETIRED_EV`".

        Claim: with ev_soh_floor_pct=80 (default), an soh_pct of exactly
        80.00 → grade=B and battery stays IDLE (not auto-retired).
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=40.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert float(b2["soh_pct"]) == pytest.approx(80.00, abs=0.001)
        assert b2["soh_grade"] == "B"
        assert b2["status"] == "IDLE"

    def test_grade_c_at_exactly_70(self, api):
        """PRD §3.5: "exactly 70.0 is C, not RETIRED_EV".

        Claim: soh_pct exactly 70.00 → grade=C and battery stays IDLE.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=35.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert float(b2["soh_pct"]) == pytest.approx(70.00, abs=0.001)
        assert b2["soh_grade"] == "C"
        assert b2["status"] == "IDLE"

    def test_grade_retired_below_floor(self, api):
        """PRD §3.5: "otherwise the grade is RETIRED_EV. When the grade is
        RETIRED_EV, the auto-transition from CHARGING to RETIRED runs".

        Claim: soh_pct below 70 → grade=RETIRED_EV and status=RETIRED
        (auto-retire).
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        b2 = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=30.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert b2["soh_grade"] == "RETIRED_EV"
        assert b2["status"] == "RETIRED"


class TestCascadeGrading:
    def test_grade_cascade_energy_storage_below_1500(self, api,
                                                    platform_admin_headers):
        """PRD §3.5: "if cycle_count is strictly less than one thousand
        five hundred, the stage is ENERGY_STORAGE".

        Claim: a RETIRED battery with cycle_count < 1500 and no recall
        graded via /grade-cascade → cascade_stage = 'ENERGY_STORAGE'.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        # Auto-retire via low capacity.
        drive_battery_to_charging(scene, b["id"])
        retired = finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=30.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        assert retired["status"] == "RETIRED"
        # PRD §3.5 says auto-retire auto-runs cascade_grading; but the
        # explicit endpoint is for cascade_stage == NONE. If the auto
        # path already populated it, this test exercises the same
        # algorithm by reading the resulting cascade_stage.
        op = make_operator_headers(scene["station"]["id"])
        fresh = api.get_battery(b["id"], op).json()["data"]
        if fresh["cascade_stage"] == "NONE":
            resp = api.grade_cascade(b["id"], platform_admin_headers)
            graded = validate_success(resp)
            assert graded["cascade_stage"] == "ENERGY_STORAGE"
        else:
            # Auto-graded path already ran the same algorithm.
            assert fresh["cascade_stage"] == "ENERGY_STORAGE"

    def test_recycle_requires_end_of_life(self, api, platform_admin_headers):
        """PRD §3.5: "Only a battery whose status is RETIRED and whose
        cascade_stage is END_OF_LIFE can be moved on to RECYCLED ...
        Attempts to recycle a battery whose cascade_stage is anything
        other than END_OF_LIFE are rejected with ERR_INVALID_STATE."

        Claim: recycle on a RETIRED battery whose cascade_stage is
        ENERGY_STORAGE → ERR_INVALID_STATE.
        """
        scene = setup_basic_scene(rated_capacity_kwh=50.0)
        b = scene["idle_batteries"][0]
        drive_battery_to_charging(scene, b["id"])
        finish_charge(
            scene, b["id"], soc_pct=100.0, capacity_test_kwh=30.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
        # Now cascade_stage should be ENERGY_STORAGE (cycle_count < 1500
        # and no recall). Recycle should refuse.
        op = make_operator_headers(scene["station"]["id"])
        fresh = api.get_battery(b["id"], op).json()["data"]
        if fresh["cascade_stage"] == "NONE":
            api.grade_cascade(b["id"], platform_admin_headers)
        resp = api.recycle_battery(b["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
