"""Crew/equipment/weather scheduling constraints, the crew-begin cross-entity
guard, the day-count conservation invariant, and a validation-priority pair.

Covers crew double-booking with the required buffer gap, equipment aggregate
capacity with closed-interval adjacency, double-booking precedence over weather,
the crew-begin IN_PROGRESS guard, scheduled-day-count conservation across
assignment cancellation, crew-skill adequacy, and exterior-weather gating.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_product, create_project, add_surface,
    create_crew, create_equipment, schedule_crew,
    setup_scheduled_project,
    TEST_DEFAULTS, TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
PM = TEST_USERS["project_manager_headers"]
CREW = TEST_USERS["crew_member_headers"]

S1_DEPOSIT = TEST_DEFAULTS["S1_DEPOSIT_30PCT_CENTS"]  # 2674


# ─── resource_temporal_overlap: crew double-book buffer gap ───────────────

def test_crew_back_to_back_assignment_rejected(api):
    """PRD §3.5: "the new window must neither overlap another `SCHEDULED` or `IN_PROGRESS`
    assignment of the same crew member nor sit immediately back-to-back with one; the
    system requires a gap of at least one clear day between two assignments of the same
    member, so adjacent windows are rejected."

    Design: Difficulty/resource_temporal_overlap/crew_double_book_buffer_gap_required
    """
    project = create_project()
    crew = create_crew()
    schedule_crew(project["id"], crew["id"], "2026-03-10", "2026-03-12")
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": crew["id"],
            "start_date": "2026-03-13",  # immediately after 03-12, no buffer
            "end_date": "2026-03-14",
        },
        PM,
    )
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


def test_crew_overlapping_assignment_rejected(api):
    """PRD §3.5: "the new window must neither overlap another `SCHEDULED` or `IN_PROGRESS`
    assignment of the same crew member nor sit immediately back-to-back with one..."

    Design: Difficulty/resource_temporal_overlap/crew_double_book_buffer_gap_required
    """
    project = create_project()
    crew = create_crew()
    schedule_crew(project["id"], crew["id"], "2026-03-10", "2026-03-12")
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": crew["id"],
            "start_date": "2026-03-11",  # overlaps [03-10, 03-12]
            "end_date": "2026-03-13",
        },
        PM,
    )
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


# ─── resource_temporal_overlap: equipment aggregate capacity ──────────────

def test_equipment_overlap_exceeds_capacity_rejected(api):
    """PRD §3.5: "across `SCHEDULED` and `IN_PROGRESS` assignments holding the same
    `equipment_id`, the peak number of date-overlapping assignments must not exceed that
    equipment's `total_units`..."

    Design: Difficulty/resource_temporal_overlap/equipment_overbook_aggregate_capacity
    """
    project = create_project()
    cm1 = create_crew()
    cm2 = create_crew(full_name="Jo Painter")
    equip = create_equipment(total_units=1)
    schedule_crew(project["id"], cm1["id"], "2026-03-10", "2026-03-12", equipment_id=equip["id"])
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": cm2["id"],
            "equipment_id": equip["id"],
            "start_date": "2026-03-11",  # overlaps -> peak 2 > 1
            "end_date": "2026-03-13",
        },
        PM,
    )
    validate_error(res, "ERR_EQUIPMENT_OVERBOOKED", expected_status=409)


def test_equipment_adjacent_assignment_allowed(api):
    """PRD §3.5: "here intervals are closed and adjacency is allowed with no buffer, so
    two assignments that merely touch at the boundary are counted by their actual date
    overlap only."

    Design: Difficulty/resource_temporal_overlap/equipment_overbook_aggregate_capacity
    """
    project = create_project()
    cm1 = create_crew()
    cm2 = create_crew(full_name="Jo Painter")
    equip = create_equipment(total_units=1)
    schedule_crew(project["id"], cm1["id"], "2026-03-10", "2026-03-12", equipment_id=equip["id"])
    # Non-overlapping window for the same single-unit equipment is accepted.
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": cm2["id"],
            "equipment_id": equip["id"],
            "start_date": "2026-03-13",
            "end_date": "2026-03-14",
        },
        PM,
    )
    asg = validate_success(res, 201)
    assert asg["status"] == "SCHEDULED"


# ─── priority pair: crew double-book (prio9) beats weather (prio11) ───────

def test_crew_double_book_beats_weather_unsuitable(api, project_manager_headers):
    """PRD §3.12: "for crew-assignment creation specifically, skill adequacy is checked,
    then double-booking, then equipment capacity, then weather."

    Design: Difficulty/priority_pair_validation_conflict/crew_assignment_temporal_beats_safety_weather
    """
    project = create_project(scope="EXTERIOR")
    crew = create_crew()  # MASTER, skill ok
    schedule_crew(project["id"], crew["id"], "2026-03-10", "2026-03-12")
    # Unsuitable weather on 03-11 (temp 40, precip 80).
    api.create_weather_window(
        {"window_date": "2026-03-11", "forecast_temp_f": 40, "precipitation_pct": 80},
        project_manager_headers,
    )
    # New window overlaps (double-book, prio9) AND requires exterior weather (prio11).
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": crew["id"],
            "start_date": "2026-03-11",
            "end_date": "2026-03-13",
            "requires_exterior_weather": True,
        },
        project_manager_headers,
    )
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


def test_crew_double_book_beats_weather_when_fully_overlapping(api, project_manager_headers):
    """PRD §3.12: "for crew-assignment creation specifically, skill adequacy is checked,
    then double-booking, then equipment capacity, then weather."

    Design: Difficulty/priority_pair_validation_conflict/crew_assignment_temporal_beats_safety_weather
    """
    project = create_project(scope="EXTERIOR")
    crew = create_crew()  # MASTER, skill ok
    schedule_crew(project["id"], crew["id"], "2026-03-10", "2026-03-12")
    # Unsuitable weather across the requested window.
    api.create_weather_window(
        {"window_date": "2026-03-10", "forecast_temp_f": 40, "precipitation_pct": 80},
        project_manager_headers,
    )
    # New window is fully contained in the existing booking (double-book, prio9) AND
    # requests exterior weather on an unsuitable day (prio11). Double-book wins.
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": crew["id"],
            "start_date": "2026-03-10",
            "end_date": "2026-03-11",
            "requires_exterior_weather": True,
        },
        project_manager_headers,
    )
    validate_error(res, "ERR_CREW_DOUBLE_BOOKED", expected_status=409)


# ─── cross_entity_state_dependency: crew begin requires project IN_PROGRESS

def test_crew_begin_requires_project_in_progress(api):
    """PRD §3.6: "Beginning an assignment moves it from `SCHEDULED` to `IN_PROGRESS`; this
    requires the assignment to be `SCHEDULED` (otherwise `ERR_ASSIGNMENT_NOT_SCHEDULED`)
    and — a cross-entity guard — the parent project to be `IN_PROGRESS` (otherwise
    `ERR_PROJECT_NOT_IN_PROGRESS`)."

    Design: Difficulty/cross_entity_state_dependency/crew_begin_requires_project_in_progress
    """
    bundle = setup_scheduled_project(S1_DEPOSIT)  # project is SCHEDULED, start-work NOT called
    res = api.begin_crew_assignment(bundle["assignment"]["id"], CREW)
    validate_error(res, "ERR_PROJECT_NOT_IN_PROGRESS", expected_status=409)


def test_crew_begin_blocked_while_project_scheduled(api):
    """PRD §3.6: "the parent project to be `IN_PROGRESS` (otherwise
    `ERR_PROJECT_NOT_IN_PROGRESS`)."

    Design: Difficulty/cross_entity_state_dependency/crew_begin_requires_project_in_progress
    """
    bundle = setup_scheduled_project(S1_DEPOSIT)
    project_before = validate_success(api.get_project(bundle["project"]["id"], PM), 200)
    assert project_before["workflow_status"] == "SCHEDULED"
    res = api.begin_crew_assignment(bundle["assignment"]["id"], CREW)
    validate_error(res, "ERR_PROJECT_NOT_IN_PROGRESS", expected_status=409)


# ─── compensating_invariant: cancel conserves scheduled_day_count ─────────

def test_assignment_cancel_restores_scheduled_day_count(api):
    """PRD §2.9: "Both counters are **conserved across the assignment lifecycle**:
    scheduling an assignment raises them, and any path that ends the commitment —
    completing the work or cancelling the assignment — releases the same quantity back, so
    the books always reconcile."
    PRD §3.6: "cancellation moves it to `CANCELLED` and likewise subtracts its `day_count`
    from the crew member's `scheduled_day_count`..."

    Design: Difficulty/compensating_invariant/crew_assignment_cancel_conserves_scheduled_day_count
    """
    project = create_project()
    crew = create_crew()
    asg = schedule_crew(project["id"], crew["id"], "2026-03-10", "2026-03-12")  # day_count 3
    after_assign = validate_success(api.get_crew_member(crew["id"], PM), 200)
    assert after_assign["scheduled_day_count"] == 3

    cancelled = validate_success(api.cancel_crew_assignment(asg["id"], PM), 200)
    assert cancelled["status"] == "CANCELLED"
    after_cancel = validate_success(api.get_crew_member(crew["id"], PM), 200)
    assert after_cancel["scheduled_day_count"] == 0


def test_assignment_day_count_raises_then_returns_to_zero(api):
    """PRD §2.9: "A crew member's `scheduled_day_count` is the total number of distinct
    scheduled days the member is committed to across assignments that are `SCHEDULED` or
    `IN_PROGRESS`."
    PRD §3.5: "On creation the crew member's `scheduled_day_count` rises by this
    `day_count`..."

    Design: Difficulty/compensating_invariant/crew_assignment_cancel_conserves_scheduled_day_count
    """
    project = create_project()
    crew = create_crew()
    before = validate_success(api.get_crew_member(crew["id"], PM), 200)
    assert before["scheduled_day_count"] == 0
    asg = schedule_crew(project["id"], crew["id"], "2026-03-10", "2026-03-12")
    assert asg["day_count"] == 3
    validate_success(api.cancel_crew_assignment(asg["id"], PM), 200)
    final = validate_success(api.get_crew_member(crew["id"], PM), 200)
    assert final["scheduled_day_count"] == 0


# ─── corner: crew skill insufficient for RESTORATION ──────────────────────

def test_crew_skill_insufficient_for_restoration(api):
    """PRD §3.5: "the crew member's skill level must meet the minimum demanded by the
    heaviest prep level among the project's `PLANNED` surfaces — a `RESTORATION` surface
    requires a `MASTER`, a `HEAVY` surface requires at least a `JOURNEYMAN`, and surfaces
    no heavier than `STANDARD` or `LIGHT` may be served by any skill level."

    Design: Corner/validations/crew_skill_insufficient_for_restoration_rejected
    """
    product = create_product()
    project = create_project()
    add_surface(project["id"], product["id"], label="Old Trim",
                area_sqft=160, coats=1, prep_level="RESTORATION")
    apprentice = create_crew(full_name="New Hand", skill_level="APPRENTICE", daily_rate_cents=20000)
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": apprentice["id"],
            "start_date": "2026-03-02",
            "end_date": "2026-03-03",
        },
        PM,
    )
    validate_error(res, "ERR_CREW_SKILL_INSUFFICIENT", expected_status=422)


# ─── corner: weather unsuitable blocks exterior assignment ────────────────

def test_weather_unsuitable_blocks_exterior_assignment(api):
    """PRD §3.5: "when `requires_exterior_weather` is true, every date from the start
    through the end must have a recorded weather window whose `exterior_suitable` flag is
    true; a missing or unsuitable day fails the booking."

    Design: Corner/validations/weather_unsuitable_blocks_exterior_assignment
    """
    project = create_project(scope="EXTERIOR")
    crew = create_crew()
    # No weather windows recorded for the requested dates.
    res = api.create_crew_assignment(
        {
            "project_id": project["id"],
            "crew_member_id": crew["id"],
            "start_date": "2026-04-10",
            "end_date": "2026-04-11",
            "requires_exterior_weather": True,
        },
        PM,
    )
    validate_error(res, "ERR_WEATHER_UNSUITABLE", expected_status=422)
