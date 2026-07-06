"""Group project scaffolding: publish, cancel cascade, shift/assignment lifecycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, make_member_headers, make_organizer_headers,
    ApiErrorId,
    create_member,
    setup_published_project_with_shift,
    setup_member_with_two_prior_noshows,
    set_clock, create_project, create_shift, publish_project,
    assign_member_to_shift,
)


# =============================================================================
# Rule 4 — transitive_cascade
# =============================================================================

def test_project_cancel_cascades_to_shift_and_assignment(api):
    """PRD §2.9: "When a GroupProject is cancelled from PLANNING or OPEN, the
    cancel cascades: every ProjectShift whose status is OPEN or FILLED
    transitions to CANCELLED, and every ShiftAssignment under a cancelled
    shift whose status is CONFIRMED transitions to CANCELLED."

    Design: Difficulty/transitive_cascade/project_cancel_cascade_depth_3
    """
    ctx = setup_published_project_with_shift(capacity=2)  # capacity 2 keeps sh OPEN post-assign
    a1 = assign_member_to_shift(ctx["volunteer"], ctx["shift"])
    cancel = get_success_data(api.cancel_group_project(
        ctx["project"]["id"],
        headers=make_organizer_headers(ctx["organizer"]["id"]),
    ))
    assert cancel["aggregate_state"] == "CANCELLED"
    shift_after = get_success_data(api.get_shift(
        ctx["shift"]["id"],
        headers=make_organizer_headers(ctx["organizer"]["id"]),
    ))
    assert shift_after["status"] == "CANCELLED"
    a1_after = get_success_data(api.get_assignment(
        a1["id"],
        headers=make_member_headers(ctx["volunteer"]["id"]),
    ))
    assert a1_after["status"] == "CANCELLED"


def test_clock_advance_past_third_shift_suspends_member(api):
    """PRD §2.11: "The moment the count reaches 3, Member.is_suspended is set to
    true as a cascading side effect of the third NO_SHOW; the transition to
    true is not a separate write step but happens in the same operation that
    produced the third strike."

    Design: Difficulty/transitive_cascade/clock_advance_noshow_cascade_depth_3
    """
    ctx = setup_member_with_two_prior_noshows()
    # Third strike — use the reserve shift pre-created in PLANNING
    a3 = assign_member_to_shift(ctx["member"], ctx["reserve_shift"])
    set_clock("2026-03-05T10:30:00Z")
    a3_after = get_success_data(api.get_assignment(
        a3["id"],
        headers=make_member_headers(ctx["member"]["id"]),
    ))
    assert a3_after["status"] == "NO_SHOW"
    m = get_success_data(api.get_member(
        ctx["member"]["id"],
        headers=make_member_headers(ctx["member"]["id"]),
    ))
    assert m["no_show_strikes"] == 3
    assert m["is_suspended"] is True


# =============================================================================
# Rule 9 — compensating_invariant on strikes
# =============================================================================

def test_cancel_confirmed_assignment_does_not_change_no_show_strikes(api):
    """PRD §2.11: "Member.no_show_strikes is a rolling 90-day count of NO_SHOW
    ShiftAssignment rows for the member — an assignment counts toward the
    tally if the sum of its shift's shift_start_utc and duration_minutes is
    at or after the cutoff obtained by subtracting 90 days from the logical
    clock."
    PRD §3.5: "A member may cancel their own CONFIRMED assignment while the
    logical clock is strictly earlier than the shift's shift_start_utc; the
    assignment transitions to CANCELLED."

    Design: Difficulty/compensating_invariant/assignment_cancel_conserves_no_show_strikes
    """
    ctx = setup_member_with_two_prior_noshows()
    strikes_before = get_success_data(api.get_member(
        ctx["member"]["id"],
        headers=make_member_headers(ctx["member"]["id"]),
    ))["no_show_strikes"]
    sh_future = ctx["sh_extra1"]
    a = assign_member_to_shift(ctx["member"], sh_future)
    cancel = get_success_data(api.cancel_shift_assignment(
        sh_future["id"], a["id"],
        headers=make_member_headers(ctx["member"]["id"]),
    ))
    assert cancel["status"] == "CANCELLED"
    strikes_after = get_success_data(api.get_member(
        ctx["member"]["id"],
        headers=make_member_headers(ctx["member"]["id"]),
    ))["no_show_strikes"]
    assert strikes_after == strikes_before, \
        "no_show_strikes changed on a CONFIRMED->CANCELLED round-trip"


# =============================================================================
# Corner — no_show_strikes 90-day window
# =============================================================================

def test_no_show_strike_ages_out_after_90_days(api):
    """PRD §2.11: "Member.no_show_strikes is a rolling 90-day count of NO_SHOW
    ShiftAssignment rows for the member — an assignment counts toward the
    tally if the sum of its shift's shift_start_utc and duration_minutes is
    at or after the cutoff obtained by subtracting 90 days from the logical
    clock. It is recomputed on every assignment status write and lazily on
    member read when any assignment's shift-end has aged out."

    Design: Corner/calculations/no_show_strikes_out_of_window_dropped
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="nswo")
    member = create_member(email_prefix="nswv")
    project = create_project(
        organizer, title="NSW",
        window_start_utc="2026-03-01T09:00:00Z",
        window_end_utc="2026-06-30T17:00:00Z",
    )
    sh1 = create_shift(organizer, project,
                       shift_start_utc="2026-03-01T09:00:00Z",
                       duration_minutes=60, capacity=1)
    publish_project(organizer, project)
    assign_member_to_shift(member, sh1)
    set_clock("2026-03-01T10:30:00Z")
    early = get_success_data(api.get_member(
        member["id"], headers=make_member_headers(member["id"]),
    ))
    assert early["no_show_strikes"] == 1
    # Advance the clock 106 days past shift-end.
    set_clock("2026-06-15T00:00:00Z")
    late = get_success_data(api.get_member(
        member["id"], headers=make_member_headers(member["id"]),
    ))
    assert late["no_show_strikes"] == 0


# =============================================================================
# Corner — expiry bubble-up
# =============================================================================

def test_clock_advance_past_latest_start_expires_open_skill_request(api):
    """PRD §2.5: "a SkillRequest whose latest_start_utc has been passed while
    its status is still OPEN transitions to EXPIRED"

    Design: Corner/state_machines/skill_request_expiry_bubble_up_on_clock_advance
    """
    set_clock("2026-03-01T09:00:00Z")
    m = create_member(email_prefix="expm1")
    r = get_success_data(api.create_skill_request(
        {"member_id": m["id"], "skill_code": "G",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-02T10:00:00Z",
         "latest_start_utc": "2026-03-02T18:00:00Z"},
        headers=make_member_headers(m["id"]),
    ))
    set_clock("2026-03-03T09:00:00Z")
    r_after = get_success_data(api.get_skill_request(
        r["id"], headers=make_member_headers(m["id"]),
    ))
    assert r_after["status"] == "EXPIRED"
