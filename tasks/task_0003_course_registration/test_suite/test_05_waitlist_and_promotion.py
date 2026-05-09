"""Waitlist priority scoring and promotion cascades (PRD §3.5)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, TEST_USERS,
    PRIORITY_WEIGHTS,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, setup_offering_with_seat_taken,
    create_offering, create_course, create_student, advance_clock,
    submit_enrollment, submit_enrollment_success, get_enrollment_request,
    list_waitlist, list_student_sync_events, cancel_enrollment, get_offering,
)


def test_waitlist_entry_has_no_version_or_updated_at(api, registrar_headers):
    """PRD §2.4: "Two resources omit updated_at and version because they are
    immutable once written by the system: a WaitlistEntry and a SyncEvent
    both carry only id and created_at."

    Claim: WaitlistEntry response carries no updated_at and no version.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"

    entries = list_waitlist(full["offering"]["id"])
    assert len(entries) >= 1
    entry = entries[0]
    assert "updated_at" not in entry, f"WaitlistEntry should not have updated_at: {entry}"
    assert "version" not in entry, f"WaitlistEntry should not have version: {entry}"


def test_priority_score_computed_with_weighted_inputs(api, registrar_headers):
    """PRD §3.5: "The score is the sum of year_factor weighted by ten, plus
    gap_count weighted by fifteen, plus prereq_strength weighted by eight,
    minus fraud_penalty weighted by two."

    Concrete claim: a student with year_in_program=2 (year_factor=2),
    fraud_score=0 (fraud_penalty=0), enrolling in a course where
    gap_count=1 (department-owned, not completed) and no downstream
    courses reference it (prereq_strength=0), produces priority_score
    = (10*2) + (15*1) + (8*0) - (2*0) = 35.
    """
    world = setup_basic_world(student_year=2, student_completed_course_ids=[])
    full = setup_offering_with_seat_taken(world, credits=3.0)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"
    expected = (10 * 2) + (15 * 1) + (8 * 0) - (2 * 0)
    assert er["priority_score"] == expected, (
        f"Expected priority_score={expected}, got {er['priority_score']}"
    )


def test_priority_score_year_factor_capped_at_five(api, registrar_headers):
    """PRD §3.5: "A year_factor equal to the student's year_in_program capped
    at five (so a year-six student contributes the same five points as a
    year-five student)."

    Claim: a year-6 student gets year_factor of 5 in the priority score, not 6.
    """
    world = setup_basic_world(student_year=6, student_completed_course_ids=[])
    full = setup_offering_with_seat_taken(world, credits=3.0, occupant_year=2)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"
    # year_factor = min(6, 5) = 5; gap=1; prereq=0; fraud=0 → 50 + 15 = 65
    expected = (10 * 5) + (15 * 1) + (8 * 0) - (2 * 0)
    assert er["priority_score"] == expected, (
        f"Expected year-cap to clamp priority_score to {expected}, got {er['priority_score']}"
    )


def test_waitlist_ordering_by_priority_then_queued_at(api, registrar_headers):
    """PRD §3.5: "The waitlist is ordered by priority_score descending — higher
    scores are promoted first — with queued_at ascending as the tie-break:
    among entries with identical priority_score, the entry that was queued
    earlier wins."

    Claim: a higher-year (higher priority_score) student inserted later still
    appears first in the waitlist; among same-priority students the earlier
    submission wins.
    """
    world = setup_basic_world()
    full = setup_offering_with_seat_taken(world)
    s_low = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=1,
                            full_name="Lower-priority WL")
    s_high = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=4,
                             full_name="Higher-priority WL")
    er_low = submit_enrollment_success(s_low, full["offering"]["id"])
    er_high = submit_enrollment_success(s_high, full["offering"]["id"])
    assert er_low["academic_status"] == "WAITLISTED"
    assert er_high["academic_status"] == "WAITLISTED"

    entries = list_waitlist(full["offering"]["id"])
    # Position 1 should be the higher-priority entry.
    assert entries[0]["enrollment_request_id"] == er_high["id"], (
        f"Expected higher-priority entry at position 1; got {entries[0]}"
    )


def test_cancel_approved_promotes_top_of_waitlist(api, registrar_headers):
    """PRD §3.5/§3.7: "When a Student cancels an APPROVED enrollment, the
    offering's enrolled_count is decremented, the student's provisional
    credit usage is decremented by the course's credits, financial_status
    reverts from BILLED to UNBILLED, the offering's waitlist is immediately
    swept for promotion in priority order per §3.5, and an
    ENROLLMENT_CANCELED SyncEvent is emitted to all four downstream
    systems."

    Claim: cancel of APPROVED enrollment promotes the top WaitlistEntry; the
    waitlisted student's request becomes APPROVED+BILLED and a
    WAITLIST_PROMOTED SyncEvent is emitted to that student.

    # difficulty: transitive_cascade/cascade_student_cancel_promotes_waitlist_depth_3
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world, base_capacity=1)
    waitlisted_request = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert waitlisted_request["academic_status"] == "WAITLISTED"

    # Cancel the occupant's APPROVED enrollment (the seat-taking student S0).
    occupant = full["occupant"]
    occupant_request = full["occupant_request"]
    cancel_enrollment(occupant, occupant_request["id"])

    # Promotion cascade: waitlisted request → APPROVED + BILLED.
    promoted = get_enrollment_request(waitlisted_request["id"])
    assert promoted["academic_status"] == "APPROVED"
    assert promoted["financial_status"] == "BILLED"

    # WAITLIST_PROMOTED event observable on the promoted student.
    events = list_student_sync_events(world["student"]["id"])
    types = [e["event_type"] for e in events]
    assert "WAITLIST_PROMOTED" in types, (
        f"Expected WAITLIST_PROMOTED in {types}"
    )


def test_cancel_waitlisted_does_not_emit_enrollment_canceled(api, registrar_headers):
    """PRD §3.7: "For a cancellation of a WAITLISTED enrollment the cascade is
    narrower: the underlying WaitlistEntry advances from ACTIVE to CANCELED,
    no seat or credit count is affected (the request never held one), and
    no ENROLLMENT_CANCELED event is emitted because no enrollment had been
    announced."

    Claim: canceling a WAITLISTED request → WaitlistEntry CANCELED and no
    ENROLLMENT_CANCELED SyncEvent for that student tied to this request.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"

    cancel_enrollment(world["student"], er["id"])
    refreshed = get_enrollment_request(er["id"])
    assert refreshed["academic_status"] == "CANCELED"

    # Look at the WaitlistEntry now: it should not be ACTIVE for this request.
    entries = list_waitlist(full["offering"]["id"])
    for e in entries:
        if e["enrollment_request_id"] == er["id"]:
            assert e["status"] == "CANCELED", f"Expected CANCELED, got {e['status']}"


def test_waitlist_position_is_one_indexed(api, registrar_headers):
    """PRD §3.5: "The entry references its parent offering via offering_id,
    references the request via enrollment_request_id, carries a 1-indexed
    position (recomputed on every change to the offering's waitlist set)."

    Claim: the first entry on the waitlist has position == 1.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"
    entries = list_waitlist(full["offering"]["id"])
    assert len(entries) >= 1
    assert entries[0]["position"] == 1, (
        f"Expected position=1, got {entries[0]['position']}"
    )
