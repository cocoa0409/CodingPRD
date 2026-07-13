"""Task coverage (planned estimate vs track-reconciled actual, with pinned per-track
rounding order) and incident effort rollups + certification currency reads."""
import pytest
from test_helpers import (
    validate_success, TEST_USERS,
    create_incident, create_active_incident, create_team_and_member,
    create_task, log_ground_track, create_certification,
    setup_task_in_progress_with_member,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]


def _in_progress_task_with_three_tracks(api, ics):
    inc, team, member, task, co = setup_task_in_progress_with_member(
        api, incident_overrides={"name": "Coverage", "ics_incident_number": ics},
        task_overrides={"segment_area_sqkm": 10.0, "planned_searcher_hours": 8})
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T10:00:00Z",
                     distance_km=5.0, duration_min=60, coverage_area_sqkm=1.23456)
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T11:00:00Z",
                     distance_km=6.0, duration_min=60, coverage_area_sqkm=2.34567)
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T12:00:00Z",
                     distance_km=7.0, duration_min=60, coverage_area_sqkm=3.45678)
    return inc, task


# --- Difficulty: dual_variant_calc / task_coverage_estimate_vs_actual_diverge ---

def test_task_estimate_coverage_from_planned_effort(api):
    """PRD §3.3: "multiply `planned_searcher_hours` by the coverage rate
    `COVERAGE_RATE_SQKM_PER_HOUR` of 0.5 square kilometers swept per searcher-hour to
    obtain a projected swept area, divide that by `segment_area_sqkm`, cap the
    resulting ratio at 1.0, multiply by 100, and round half up to two decimal places."

    Design: Difficulty/dual_variant_calc/task_coverage_estimate_vs_actual_diverge
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc, team, member, task, co = setup_task_in_progress_with_member(
        api, incident_overrides={"name": "Canyon Search", "ics_incident_number": "OR-2026-0002"},
        task_overrides={"segment_area_sqkm": 10.0, "planned_searcher_hours": 8})
    # (8 * 0.5) / 10 = 0.4 -> 40.00%
    assert task["estimated_coverage_pct"] == pytest.approx(40.00, abs=0.001)


def test_task_actual_coverage_from_tracks_diverges_from_estimate(api):
    """PRD §3.3: "for each `GroundTrack` recorded against the task, compute that
    track's coverage fraction as its `coverage_area_sqkm` divided by the task's
    `segment_area_sqkm`, and round that fraction half up to four decimal places; then
    sum those per-track fractions; then cap the sum at 1.0; then multiply by 100 and
    round half up to two decimal places."

    Design: Difficulty/dual_variant_calc/task_coverage_estimate_vs_actual_diverge
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc, task = _in_progress_task_with_three_tracks(api, "OR-2026-0002b")
    debriefed = validate_success(api.debrief_task(task["id"], IC))
    assert debriefed["actual_coverage_pct"] == pytest.approx(70.38, abs=0.001)
    assert debriefed["estimated_coverage_pct"] != debriefed["actual_coverage_pct"]


# --- Difficulty: combinatorial_formula / coverage_per_track_rounding_order_mode_b ---

def test_actual_coverage_rounds_each_track_before_summing(api):
    """PRD §3.3: "The per-track fractions are each rounded first and only then summed
    — rounding per track before summing, never summing before rounding — because the
    two orders can differ in the last cent of a percent."

    Design: Difficulty/combinatorial_formula/coverage_per_track_rounding_order_mode_b
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc, task = _in_progress_task_with_three_tracks(api, "OR-2026-0004")
    debriefed = validate_success(api.debrief_task(task["id"], IC))
    assert debriefed["actual_coverage_pct"] == pytest.approx(70.38, abs=0.001)


def test_actual_coverage_pinned_order_is_not_sum_then_round(api):
    """PRD §3.3: "The per-track fractions are each rounded first and only then summed
    — rounding per track before summing, never summing before rounding — because the
    two orders can differ in the last cent of a percent."

    Design: Difficulty/combinatorial_formula/coverage_per_track_rounding_order_mode_b
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc, task = _in_progress_task_with_three_tracks(api, "OR-2026-0004b")
    debriefed = validate_success(api.debrief_task(task["id"], IC))
    # sum-then-round would give 70.37; the pinned round-per-track order gives 70.38.
    assert debriefed["actual_coverage_pct"] != pytest.approx(70.37, abs=0.001)
    assert debriefed["actual_coverage_pct"] == pytest.approx(70.38, abs=0.001)


# --- Corner: calculations ---

def test_incident_rollup_empty_set_is_zero(api):
    """PRD §3.1: "These rollups are also refreshed whenever a new ground track is
    created, and they read as zero for an incident whose tasks carry no tracks."

    Design: Corner/calculations/incident_rollup_empty_set_is_zero
    """
    inc = create_incident(api, name="Empty Inc", incident_type="URBAN",
                          ics_incident_number="OR-2026-1006")
    data = validate_success(api.get_incident(inc["id"], COORD))
    assert data["total_logged_hours"] == 0
    assert data["total_mileage_miles"] == 0
    assert data["active_task_count"] == 0


def test_incident_rollup_recomputes_on_track_add(api):
    """PRD §3.1: "`total_logged_hours` is the sum of `duration_min` across every
    `GroundTrack` recorded on any task of this incident divided by 60, rounded half
    up to two decimal places; `total_mileage_miles` is the sum of `distance_km`
    across those same tracks multiplied by `0.621371`, rounded half up to a whole
    number."

    Design: Corner/calculations/incident_rollup_recomputes_on_track_add
    """
    inc = create_active_incident(api, name="Roll Inc", ics_incident_number="OR-2026-1007")
    team, member = create_team_and_member(api)
    task = create_task(api, inc["id"])
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T10:00:00Z",
                     distance_km=30.0, duration_min=90, coverage_area_sqkm=2.0)
    data = validate_success(api.get_incident(inc["id"], COORD))
    assert data["total_logged_hours"] == pytest.approx(1.5, abs=0.001)  # 90/60
    assert data["total_mileage_miles"] == 19  # round_half_up(30 * 0.621371)


def test_certification_valid_strictly_before_inclusive_expiry(api):
    """PRD §3.2: "The boundary is inclusive on expiry — a certification whose
    `expires_date` exactly equals the current logical-clock instant is already
    `EXPIRED`, because expiry takes effect at the very start of the expiry instant."

    Design: Corner/calculations/certification_valid_before_expiry
    """
    api.set_clock({"to_iso8601": "2026-05-31T23:59:59Z"}, COORD)
    team, member = create_team_and_member(api, member_overrides={"full_name": "Cal Med"})
    cert = create_certification(api, member["id"], cert_type="WFR",
                                issued_date="2024-06-01T00:00:00Z",
                                expires_date="2026-06-01T00:00:00Z")
    data = validate_success(api.get_certification(cert["id"], COORD))
    assert data["status"] == "VALID"
