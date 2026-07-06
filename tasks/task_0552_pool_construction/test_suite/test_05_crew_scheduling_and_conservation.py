"""Crew booking: interval validity, temporal guards, ownership, and hour conservation."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_crew_assignment_payload,
    make_subcontractor_headers,
    setup_permitted_project_gate_and_sub, setup_two_subs_one_booked,
    setup_crew_booked_on_pending_gate, setup_permitted_project_with_suspended_sub,
    setup_sub_booked_two_projects, setup_gunite_crew_booked, setup_crew_booked_8h,
)


def test_crew_end_not_after_start_rejected(api, builder_headers):
    """PRD §2.6: "For a crew booking specifically, end_at must be strictly after start_at; when it
    is not, the dedicated code ERR_INVALID_INTERVAL (422) is returned."

    Design: Corner/validations/crew_end_not_after_start_invalid_interval
    """
    project, gate, sub = setup_permitted_project_gate_and_sub()
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub["id"], gate["id"],
                                       "2026-06-01T08:00:00Z", "2026-06-01T08:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_INTERVAL)


def test_site_occupancy_capacity_one(api, builder_headers):
    """PRD §3.5: "the site has an aggregate capacity of one crew at a time".
    PRD §3.5: "else ERR_SITE_OCCUPIED, under the same half-open, adjacency-allowed rule."

    Design: Corner/validations/site_occupied_overlap_same_project
    """
    project, gate, sub1, sub2, assignment1 = setup_two_subs_one_booked()
    # A different sub, same site, overlapping [12:00,20:00) vs [08:00,16:00).
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub2["id"], gate["id"],
                                       "2026-06-01T12:00:00Z", "2026-06-01T20:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_SITE_OCCUPIED)


def test_complete_crew_gate_not_active_rejected(api):
    """PRD §3.5: "it requires the referenced phase gate to be actively under way, meaning the
    gate's status is IN_PROGRESS or INSPECTION_PENDING; a completion against a gate in any other
    status is rejected with ERR_PHASE_NOT_ACTIVE."

    Design: Corner/state_machines/crew_complete_gate_not_active_rejected
    """
    project, gate, sub, assignment = setup_crew_booked_on_pending_gate()  # gate PENDING
    res = api.transition_crew_assignment(assignment["id"], {"action": "COMPLETE"},
                                         make_subcontractor_headers(sub["id"]))
    validate_error(res, ApiErrorId.ERR_PHASE_NOT_ACTIVE)


def test_booking_suspended_subcontractor_rejected(api, builder_headers):
    """PRD §3.5: "A booking that references a SUSPENDED sub is rejected with
    ERR_SUBCONTRACTOR_INACTIVE."

    Design: Difficulty/cross_entity_state_dependency/crew_create_requires_active_subcontractor
    """
    project, gate, sub = setup_permitted_project_with_suspended_sub()
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub["id"], gate["id"],
                                       "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_SUBCONTRACTOR_INACTIVE)


def test_booking_succeeds_once_subcontractor_reactivated(api, builder_headers):
    """PRD §3.5: "The builder may suspend a sub, moving ACTIVE to SUSPENDED, and later reactivate
    it, moving SUSPENDED back to ACTIVE. A booking that references a SUSPENDED sub is rejected with
    ERR_SUBCONTRACTOR_INACTIVE."

    Design: Difficulty/cross_entity_state_dependency/crew_create_requires_active_subcontractor
    """
    project, gate, sub = setup_permitted_project_with_suspended_sub()
    validate_success(api.transition_subcontractor(sub["id"], {"action": "REACTIVATE"}, builder_headers), 200)
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub["id"], gate["id"],
                                       "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z"),
        builder_headers)
    booking = validate_success(res, 201)
    assert booking["status"] == "SCHEDULED"


def test_same_subcontractor_overlap_double_booked(api, builder_headers):
    """PRD §3.5: "treating the interval as half-open, exact adjacency where one booking's end
    equals another's start is allowed, but any true overlap is rejected with
    ERR_SUBCONTRACTOR_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/subcontractor_double_booked_half_open
    """
    project_a, project_b, gate_a, gate_b, sub, assignment_a = setup_sub_booked_two_projects()
    # Same sub, a DIFFERENT site, overlapping [12:00,20:00) vs [08:00,16:00).
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project_b["id"], sub["id"], gate_b["id"],
                                       "2026-06-01T12:00:00Z", "2026-06-01T20:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_SUBCONTRACTOR_DOUBLE_BOOKED)


def test_same_subcontractor_adjacent_booking_allowed(api, builder_headers):
    """PRD §3.5: "treating the interval as half-open, exact adjacency where one booking's end
    equals another's start is allowed, but any true overlap is rejected with
    ERR_SUBCONTRACTOR_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/subcontractor_double_booked_half_open
    """
    project_a, project_b, gate_a, gate_b, sub, assignment_a = setup_sub_booked_two_projects()
    # Adjacency: new start (16:00) equals prior booking's end (16:00) — allowed under half-open.
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project_b["id"], sub["id"], gate_b["id"],
                                       "2026-06-01T16:00:00Z", "2026-06-02T00:00:00Z"),
        builder_headers)
    booking = validate_success(res, 201)
    assert booking["status"] == "SCHEDULED"


def test_plaster_before_cure_buffer_rejected(api, builder_headers):
    """PRD §3.5: "Third, a curing buffer protects fresh gunite: a booking for a gate in the PLASTER
    phase must start at least 24 hours after the end_at of any non-CANCELLED booking for a
    GUNITE-phase gate on the same site; a plaster crew that would start sooner is rejected with
    ERR_CURE_BUFFER."

    Design: Difficulty/resource_temporal_overlap/plaster_cure_buffer_gap
    """
    project, pg_gunite, pg_plaster, sub_gunite, sub_plaster, gunite_asg = setup_gunite_crew_booked()
    # Gunite crew ends 06-10 16:00; plaster starts 06-10 20:00 — only 4h later.
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub_plaster["id"], pg_plaster["id"],
                                       "2026-06-10T20:00:00Z", "2026-06-11T04:00:00Z"),
        builder_headers)
    validate_error(res, ApiErrorId.ERR_CURE_BUFFER)


def test_plaster_after_full_cure_buffer_allowed(api, builder_headers):
    """PRD §3.5: "a booking for a gate in the PLASTER phase must start at least 24 hours after the
    end_at of any non-CANCELLED booking for a GUNITE-phase gate on the same site; a plaster crew
    that would start sooner is rejected with ERR_CURE_BUFFER."

    Design: Difficulty/resource_temporal_overlap/plaster_cure_buffer_gap
    """
    project, pg_gunite, pg_plaster, sub_gunite, sub_plaster, gunite_asg = setup_gunite_crew_booked()
    # Gunite crew ends 06-10 16:00; plaster starts exactly 24h later at 06-11 16:00 — allowed.
    res = api.create_crew_assignment(
        create_crew_assignment_payload(project["id"], sub_plaster["id"], pg_plaster["id"],
                                       "2026-06-11T16:00:00Z", "2026-06-11T20:00:00Z"),
        builder_headers)
    booking = validate_success(res, 201)
    assert booking["status"] == "SCHEDULED"


def test_booking_adds_committed_hours(api, builder_headers):
    """PRD §3.5: "The booking's duration_hours is computed as the total seconds between start_at
    and end_at divided by 3600, expressed in hours to two decimal places."
    PRD §3.5: "Creating a booking adds exactly that booking's duration_hours to the total".

    Design: Difficulty/compensating_invariant/crew_cancel_conserves_committed_crew_hours
    """
    project, gate, sub, assignment = setup_crew_booked_8h()
    assert assignment["duration_hours"] == pytest.approx(8.0, abs=0.01)
    sub_after = validate_success(api.get_subcontractor(sub["id"], builder_headers), 200)
    assert sub_after["committed_crew_hours"] == pytest.approx(8.0, abs=0.01)


def test_cancel_restores_committed_hours(api, builder_headers):
    """PRD §3.5: "Creating a booking adds exactly that booking's duration_hours to the total;
    cancelling a booking subtracts exactly the same duration_hours back out, so that a
    create-then-cancel pair leaves committed_crew_hours unchanged."

    Design: Difficulty/compensating_invariant/crew_cancel_conserves_committed_crew_hours
    """
    project, gate, sub, assignment = setup_crew_booked_8h()
    before = validate_success(api.get_subcontractor(sub["id"], builder_headers), 200)
    assert before["committed_crew_hours"] == pytest.approx(8.0, abs=0.01)
    validate_success(api.transition_crew_assignment(assignment["id"], {"action": "CANCEL"},
                                                    make_subcontractor_headers(sub["id"])), 200)
    after = validate_success(api.get_subcontractor(sub["id"], builder_headers), 200)
    assert after["committed_crew_hours"] == pytest.approx(0.0, abs=0.01)
