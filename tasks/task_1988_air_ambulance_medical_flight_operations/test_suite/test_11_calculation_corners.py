"""Calculation corner claims: weather constant table branches, ICE override,
acuity tier boundary, provisional ground-leg inclusion filter."""
import pytest

from test_helpers import (
    advance_ground_leg,
    api_client,
    create_ground_leg,
    create_invoice,
    create_mission_request,
    create_patient,
    get_success_data,
    post_weather,
    set_clock,
    setup_planning_mission,
    triage_request,
    TEST_USERS,
)

DISP = TEST_USERS["dispatcher_headers"]


class TestWeatherFixedWingNightMountainousNoGo:
    def test_fixed_wing_night_with_mountain_bonus_requires_1700_ft(self):
        """PRD §3.4: "The required ceiling is the base ceiling for the assigned
        tail's class and the light condition — 500 feet for a rotor-wing by day,
        800 for a rotor-wing by night, 800 for a fixed-wing by day, 1,200 for a
        fixed-wing by night — plus a further 500 feet when the `terrain` is
        `MOUNTAINOUS`."
        PRD §3.4: "The decision is `NO_GO` when any of the following holds: ...
        the ceiling is strictly below the required ceiling."

        Design: Corner/calculations/weather_fixed_wing_night_mountainous_nogo
        """
        ctx = setup_planning_mission(
            subscales={"cardio": 2, "resp": 1, "neuro": 1, "interv": 0},
            tier="BLS",
            aircraft_class="FIXED_WING",
            medical_config="BLS_CAPABLE",
            estimated_loaded_miles=200,
            planned_launch_iso="2026-08-01T22:00:00Z",
            planned_duration_min=180,
            origin_facility="Clinic West",
        )
        pilot = ctx["roster"]["PILOT"]
        # FIXED_WING NIGHT base 1200 + MOUNTAINOUS 500 = 1700 required; 1600 < 1700.
        wa = post_weather(
            ctx["mission"]["id"], ctx["mission"]["version"], pilot,
            ceiling_ft=1600, visibility_sm=5.0, wind_kt=10,
            day_night="NIGHT", terrain="MOUNTAINOUS",
        )
        assert wa["decision"] == "NO_GO", (
            f"1600 ft is strictly below the 1700 ft requirement, got {wa['decision']}"
        )


class TestWeatherIcePrecipForcesNoGo:
    def test_ice_overrides_otherwise_perfect_conditions(self):
        """PRD §3.4: "The decision is `NO_GO` when any of the following holds:
        the `precip` is `ICE`; the crosswind strictly exceeds the maximum; the
        ceiling is strictly below the required ceiling; or the visibility is
        strictly below the required visibility."

        Design: Corner/calculations/weather_ice_precip_forces_nogo
        """
        ctx = setup_planning_mission(
            transport_class="EMERGENCY_SCENE", origin_facility="Scene"
        )
        pilot = ctx["roster"]["PILOT"]
        wa = post_weather(
            ctx["mission"]["id"], ctx["mission"]["version"], pilot,
            ceiling_ft=5000, visibility_sm=10.0, wind_kt=3, precip="ICE",
        )
        assert wa["decision"] == "NO_GO", (
            f"precip ICE is an unconditional NO_GO override, got {wa['decision']}"
        )


class TestAcuityTierBoundaryExactly4MapsAls:
    def test_acceptance_score_exactly_4_is_als(self):
        """PRD §3.2: "The acceptance score fixes the request's `acuity_tier`: a
        score of at least 7.0 is `CCT`, at least 4.0 but below 7.0 is `ALS`, and
        anything below 4.0 is `BLS`, with both breaks inclusive."
        PRD §3.2: "An onset exactly 120 minutes before scoring earns no bonus."

        Design: Corner/calculations/acuity_tier_boundary_exactly_4_maps_als
        """
        set_clock("2026-08-01T00:00:00Z")
        patient = create_patient(full_name="Edge Case", date_of_birth="1977-07-07", weight_kg=77)
        # Onset 10 hours before scoring: no deterioration bonus.
        request = create_mission_request(
            patient["id"],
            subscales={"cardio": 4, "resp": 4, "neuro": 4, "interv": 4},
            onset_iso="2026-07-31T14:00:00Z",
            origin_facility="Clinic West",
        )
        request = triage_request(
            request["id"], subscales={"cardio": 4, "resp": 4, "neuro": 4, "interv": 4}
        )
        # 4*.25+4*.35+4*.25+4*.15 = 1.0+1.4+1.0+0.6 = 4.00; no bonus (600 min >= 120).
        assert request["acceptance_acuity_score"] == pytest.approx(4.0, abs=1e-9)
        assert request["acuity_tier"] == "ALS", (
            f"4.0 >= 4.0 inclusive maps ALS (below 7.0), got {request['acuity_tier']}"
        )


class TestProvisionalGroundLegInclusionExcludesCancelled:
    def test_provisional_ground_line_counts_scheduled_but_not_cancelled(self):
        """PRD §3.8: "The provisional quote, computed at creation while actuals
        are unknown, takes the mission's `estimated_loaded_miles`, multiplies it
        by a 1.15 pad factor, and rounds up to the next whole mile; it counts
        every ground leg in `SCHEDULED`, `ENROUTE`, `AT_BEDSIDE`, or
        `COMPLETED`."
        PRD §3.8: "The `ground_line_cents` is a flat 45,000 cents ($450.00) per
        included ground leg."

        Design: Corner/calculations/provisional_ground_leg_inclusion_excludes_cancelled
        """
        ctx = setup_planning_mission(estimated_loaded_miles=10, planned_duration_min=90)
        mission = ctx["mission"]
        create_ground_leg(mission["id"], leg_type="DESTINATION", provider_name="City EMS")
        leg_b = create_ground_leg(
            mission["id"], leg_type="DESTINATION", provider_name="County Ambulance",
            scheduled_pickup_iso="2026-08-01T09:15:00Z",
        )
        advance_ground_leg(leg_b["id"], "CANCELLED")
        invoice = create_invoice(mission["id"])
        # Only the SCHEDULED leg A is included; CANCELLED leg B excluded.
        assert invoice["ground_line_cents"] == 45000, (
            f"Expected ground line 45000 (one included leg), got {invoice['ground_line_cents']}"
        )
        # est 10 -> ceil(10*1.15)=12 miles; 12*16000=192,000 mileage;
        # fuel round(192,000*0.07)=13,440; subtotal 1,800,000+192,000+13,440+120,000
        # = 2,125,440 < 2,500,000 -> logistics 0; total 2,125,440+45,000 = 2,170,440.
        assert invoice["provisional_total_cents"] == 2170440, (
            f"Expected provisional 2170440, got {invoice['provisional_total_cents']}"
        )
