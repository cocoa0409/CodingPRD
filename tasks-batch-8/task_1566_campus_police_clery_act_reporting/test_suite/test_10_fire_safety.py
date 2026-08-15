"""Fire incident and fire safety report tests (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_geography, create_fire_incident, finalize_fire_incident,
    create_fire_report, create_compiled_fire_report, create_published_fire_report,
    ApiErrorId, assert_fire_incident, assert_fire_report, TEST_USERS,
)

CHIEF = TEST_USERS["chief_headers"]
COORD = TEST_USERS["coordinator_headers"]


def test_fire_damage_per_incident_round_then_sum(api):
    """PRD §2.7: "Fire damage is the one rounded quantity in the system:
    adjudicated damage is rounded half up to zero decimal places — whole
    dollars — at the moment a fire incident is finalized, and the rounded
    per-incident value is persisted before any aggregation. Fire report totals
    sum the already-rounded per-incident values; the sum itself is never
    rounded."
    PRD §3.8: "`total_damage_dollars` is the sum of their already-rounded
    `final_damage_dollars` values — round per incident, then sum, never round
    the sum."

    Design: Difficulty/combinatorial_formula/fire_damage_per_incident_round_then_sum
    """
    geography = create_geography(
        name="Residence Hall B", category="ON_CAMPUS_RESIDENTIAL", is_residential_facility=True
    )
    fsr = create_fire_report(report_year=2026)

    fire_a = create_fire_incident(
        geography["id"], occurred_at="2026-05-01T02:00:00Z",
        cause_category="COOKING", injuries=0, deaths=0,
        estimated_damage_dollars=120.00,
    )
    fire_b = create_fire_incident(
        geography["id"], occurred_at="2026-05-20T02:00:00Z",
        cause_category="ELECTRICAL", injuries=1, deaths=0,
        estimated_damage_dollars=80.25,
    )
    finalized_a = finalize_fire_incident(fire_a["id"], 100.50)
    finalized_b = finalize_fire_incident(fire_b["id"], 100.50)
    assert finalized_a["final_damage_dollars"] == 101, "round_half_up(100.50) == 101"
    assert finalized_b["final_damage_dollars"] == 101

    compiled = validate_success(api.compile_fire_report(fsr["id"], COORD), 200)
    assert compiled["total_damage_dollars"] == 202, (
        "Per-incident round (101 + 101) then sum = 202; round-of-sum would give 201"
    )
    assert compiled["total_fires"] == 2
    assert compiled["total_injuries"] == 1
    assert compiled["total_deaths"] == 0
    assert compiled["provisional_total_damage_dollars"] == 0, (
        "No REPORTED incidents remain, so the provisional family totals zero"
    )


def test_fire_damage_round_half_up_boundary(api):
    """PRD §3.8: "the system rounds that value half up to zero decimal places,
    persists the whole-dollar result as `final_damage_dollars`, and moves the
    incident to `FINALIZED`."

    Design: Difficulty/combinatorial_formula/fire_damage_per_incident_round_then_sum
    """
    geography = create_geography(
        name="Residence Hall B2", category="ON_CAMPUS_RESIDENTIAL",
        is_residential_facility=True,
    )
    # 100.49 rounds down to 100 under round-half-up.
    fire = create_fire_incident(
        geography["id"], occurred_at="2026-05-02T02:00:00Z",
        cause_category="HEATING", estimated_damage_dollars=100.49,
    )
    finalized = finalize_fire_incident(fire["id"], 100.49)
    assert finalized["final_damage_dollars"] == 100, (
        "round_half_up(100.49) == 100 (just below the .5 boundary)"
    )


def test_fire_finalize_cascade_depth2(api):
    """PRD §3.8: "Both finalize and begin-adjustment fire a two-link cascade
    into the year's fire safety report: the `FireSafetyReport` for the calendar
    year of `occurred_at`, if it exists and has been compiled at least once,
    gets `totals_stale` true; and if that report's status is `PUBLISHED` or
    `REPUBLISHED`, it automatically transitions to `UNDER_AMENDMENT`."

    Design: Difficulty/transitive_cascade/fire_finalize_cascade_depth2
    """
    geography = create_geography(
        name="Residence Hall C", category="ON_CAMPUS_RESIDENTIAL",
        is_residential_facility=True,
    )
    fsr = create_published_fire_report(report_year=2026)
    assert fsr["status"] == "PUBLISHED"

    fire = create_fire_incident(
        geography["id"], occurred_at="2026-06-10T03:00:00Z",
        cause_category="SMOKING_MATERIALS", injuries=0, deaths=0,
        estimated_damage_dollars=480.00,
    )
    finalized = finalize_fire_incident(fire["id"], 500)
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_damage_dollars"] == 500

    fsr_after = validate_success(api.get_fire_report(fsr["id"], COORD), 200)
    assert fsr_after["totals_stale"] is True, "Cascade link 1: finalize flips totals_stale"
    assert fsr_after["status"] == "UNDER_AMENDMENT", (
        "Cascade link 2: a PUBLISHED report auto-transitions to UNDER_AMENDMENT"
    )


def test_fire_finalize_stale_without_published_report(api):
    """PRD §3.8: "the `FireSafetyReport` for the calendar year of
    `occurred_at`, if it exists and has been compiled at least once, gets
    `totals_stale` true; and if that report's status is `PUBLISHED` or
    `REPUBLISHED`, it automatically transitions to `UNDER_AMENDMENT`."

    A compiled-but-not-published report gains totals_stale without an
    auto-transition.

    Design: Difficulty/transitive_cascade/fire_finalize_cascade_depth2
    """
    geography = create_geography(
        name="Residence Hall C2", category="ON_CAMPUS_RESIDENTIAL",
        is_residential_facility=True,
    )
    fsr = create_compiled_fire_report(report_year=2026)
    assert fsr["status"] == "COMPILED"

    fire = create_fire_incident(
        geography["id"], occurred_at="2026-06-11T03:00:00Z",
        cause_category="OPEN_FLAME", estimated_damage_dollars=75.00,
    )
    finalize_fire_incident(fire["id"], 80)

    fsr_after = validate_success(api.get_fire_report(fsr["id"], COORD), 200)
    assert fsr_after["totals_stale"] is True
    assert fsr_after["status"] == "COMPILED", (
        "Only PUBLISHED/REPUBLISHED reports auto-transition to UNDER_AMENDMENT"
    )


def test_fire_incident_requires_residential_facility(api):
    """PRD §3.8: "The referenced geography must satisfy two constraints beyond
    existence: its `status` must be `ACTIVE` per the general rule, and
    `is_residential_facility` must be true — a fire reported against a
    non-residential zone is rejected with `ERR_RESIDENTIAL_FACILITY_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/fire_incident_requires_residential_facility
    """
    geography = create_geography(
        name="Academic Hall", category="ON_CAMPUS", is_residential_facility=False
    )
    res = api.create_fire_incident(
        {
            "geography_id": geography["id"],
            "occurred_at": "2026-05-01T01:00:00Z",
            "cause_category": "ELECTRICAL",
            "estimated_damage_dollars": 100,
        },
        CHIEF,
    )
    validate_error(res, ApiErrorId.ERR_RESIDENTIAL_FACILITY_REQUIRED.value,
                   expected_status=422)


def test_fire_provisional_totals_include_unfinalized_estimates(api):
    """PRD §3.8: "The provisional family is always computed alongside:
    `provisional_total_damage_dollars` sums the unrounded
    `estimated_damage_dollars` over the year's incidents currently in
    `REPORTED` status only, so the same incident population can contribute
    different totals to the two figures."
    PRD §3.8: "Incidents in `REPORTED` or `UNDER_ADJUSTMENT` contribute nothing
    to the final family."

    Design: Corner/calculations/fire_provisional_totals_include_unfinalized_estimates
    """
    geography = create_geography(
        name="Hall D", category="ON_CAMPUS_RESIDENTIAL", is_residential_facility=True
    )
    fsr = create_fire_report(report_year=2026)
    create_fire_incident(
        geography["id"], occurred_at="2026-03-03T01:00:00Z",
        cause_category="OPEN_FLAME", injuries=2, deaths=0,
        estimated_damage_dollars=250.75,
    )

    compiled = validate_success(api.compile_fire_report(fsr["id"], COORD), 200)
    assert compiled["status"] == "COMPILED"
    assert compiled["total_fires"] == 0
    assert compiled["total_damage_dollars"] == 0
    assert compiled["total_injuries"] == 0
    assert compiled["provisional_total_damage_dollars"] == pytest.approx(250.75, abs=0.001), (
        "Provisional family sums the unrounded estimate over REPORTED incidents"
    )
