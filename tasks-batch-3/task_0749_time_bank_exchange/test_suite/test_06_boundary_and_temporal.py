"""Boundary tests (fiscal, ratio) and temporal-overlap gates (shift, exchange)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_member_headers, make_organizer_headers,
    ApiErrorId,
    create_member, seed_balance,
    setup_two_members_and_offer, setup_published_project_with_shift,
    set_clock, create_project, create_shift, publish_project,
    assign_member_to_shift, create_offer, create_request, create_exchange,
    setup_scheduled_exchange,
)


# =============================================================================
# Rule 6 — boundary_precision_check
# =============================================================================

def test_exchange_create_accepted_when_balance_exactly_matches_committed(api):
    """PRD §3.3: "The requester's forward_looking_balance_minutes must be at
    least committed_minutes, so that the pending debit implied by the booking
    cannot overdraw the account beyond commitments already in flight; a
    shortfall is rejected with ERR_INSUFFICIENT_BALANCE."

    Design: Difficulty/boundary_precision_check/insufficient_balance_boundary_exact_gte_on_exchange_create
    """
    ctx = setup_two_members_and_offer(requester_seed=60, offer_minutes=60)
    req = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": req["id"],
         "scheduled_start_utc": "2026-03-05T10:00:00Z", "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    ex = validate_success(resp, expected_status=201)
    assert ex["status"] == "SCHEDULED"
    # Pending debit drops forward-looking to zero
    m = get_success_data(api.get_member(
        ctx["requester"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    assert m["forward_looking_balance_minutes"] == 0


def test_project_completion_ratio_exactly_meets_minimum_transitions_completed(api):
    """PRD §2.9: "if the ratio is at least the minimum, the state is COMPLETED,
    otherwise it is CANCELLED"
    PRD §2.10: "GroupProject.minimum_completed_ratio is a decimal with two
    fractional digits, and the completion-ratio comparison against it uses
    round-half-up at two decimal places before the >= test."

    Design: Difficulty/boundary_precision_check/project_completion_ratio_boundary_exactly_meets
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="org")
    vols = [create_member(email_prefix=f"v{i}") for i in range(5)]
    project = create_project(
        organizer, title="B2",
        window_start_utc="2026-03-02T09:00:00Z",
        window_end_utc="2026-03-04T17:00:00Z",
        minimum_completed_ratio=0.60,
    )
    shifts = [
        create_shift(organizer, project,
                     shift_start_utc=start,
                     duration_minutes=60, capacity=1,
                     role_label="P")
        for start in [
            "2026-03-02T09:00:00Z",
            "2026-03-02T11:00:00Z",
            "2026-03-02T13:00:00Z",
            "2026-03-03T09:00:00Z",
            "2026-03-03T11:00:00Z",
        ]
    ]
    publish_project(organizer, project)
    for v, sh in zip(vols, shifts):
        assign_member_to_shift(v, sh)
    # Check in only the first three volunteers -> 3 COMPLETED shifts of 5
    check_ins = [
        ("2026-03-02T09:30:00Z", 0),
        ("2026-03-02T11:30:00Z", 1),
        ("2026-03-02T13:30:00Z", 2),
    ]
    for advance_to, idx in check_ins:
        set_clock(advance_to)
        get_success_data(api.check_in_assignment(
            _first_assignment(api, shifts[idx]["id"])["id"],
            headers=make_member_headers(vols[idx]["id"]),
        ))
    # Roll the clock past the third shift's end so it flips to COMPLETED.
    set_clock("2026-03-02T14:30:00Z")
    # Now roll past window_end_utc so the aggregate-state resolver evaluates ratio
    set_clock("2026-03-04T17:30:00Z")
    resp = api.get_group_project(
        project["id"], headers=make_organizer_headers(organizer["id"]),
    )
    data = validate_success(resp)
    assert data["aggregate_state"] == "COMPLETED"


def _first_assignment(api, shift_id):
    resp = api.list_shift_assignments(shift_id, headers=TEST_USERS["admin_headers"])
    from test_helpers import validate_paginated as _vp
    data, _ = _vp(resp)
    assert len(data) >= 1
    return data[0]


# =============================================================================
# Rule 8 — resource_temporal_overlap
# =============================================================================

def test_shift_assignments_touching_endpoints_are_allowed(api):
    """PRD §2.11: "for a shift assignment, the requested assignment's interval —
    closed on the left at shift_start_utc, open on the right at
    shift_start_utc + duration_minutes — must not overlap another CONFIRMED
    or CHECKED_IN assignment held by the same member, with intervals touching
    at the endpoints allowed"

    Design: Difficulty/resource_temporal_overlap/shift_assignment_overlap_touching_endpoints_ok
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="ov1o")
    volunteer = create_member(email_prefix="ov1v")
    project = create_project(
        organizer, title="OV1",
        window_start_utc="2026-03-05T09:00:00Z",
        window_end_utc="2026-03-05T17:00:00Z",
    )
    sh1 = create_shift(organizer, project,
                       shift_start_utc="2026-03-05T09:00:00Z",
                       duration_minutes=30, capacity=2)
    sh2 = create_shift(organizer, project,
                       shift_start_utc="2026-03-05T09:30:00Z",
                       duration_minutes=30, capacity=2)
    publish_project(organizer, project)
    get_success_data(api.create_shift_assignment(
        sh1["id"], {"member_id": volunteer["id"]},
        headers=make_member_headers(volunteer["id"]),
    ))
    resp = api.create_shift_assignment(
        sh2["id"], {"member_id": volunteer["id"]},
        headers=make_member_headers(volunteer["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "CONFIRMED"


def test_true_overlap_between_shift_assignments_rejected(api):
    """PRD §2.11: "for a shift assignment, the requested assignment's interval —
    closed on the left at shift_start_utc, open on the right at
    shift_start_utc + duration_minutes — must not overlap another CONFIRMED
    or CHECKED_IN assignment held by the same member, with intervals touching
    at the endpoints allowed; a violation is rejected with
    ERR_SHIFT_TIME_CONFLICT."

    Design: Corner/errors/err_shift_time_conflict_true_overlap
    """
    set_clock("2026-03-01T09:00:00Z")
    organizer = create_member(email_prefix="stco")
    volunteer = create_member(email_prefix="stcv")
    project = create_project(
        organizer, title="STC",
        window_start_utc="2026-03-05T09:00:00Z",
        window_end_utc="2026-03-05T17:00:00Z",
    )
    sh1 = create_shift(organizer, project,
                       shift_start_utc="2026-03-05T09:00:00Z",
                       duration_minutes=60, capacity=2)
    sh2 = create_shift(organizer, project,
                       shift_start_utc="2026-03-05T09:30:00Z",
                       duration_minutes=60, capacity=2)
    publish_project(organizer, project)
    get_success_data(api.create_shift_assignment(
        sh1["id"], {"member_id": volunteer["id"]},
        headers=make_member_headers(volunteer["id"]),
    ))
    resp = api.create_shift_assignment(
        sh2["id"], {"member_id": volunteer["id"]},
        headers=make_member_headers(volunteer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_CONFLICT)


def test_exchange_with_30min_travel_buffer_conflicts(api):
    """PRD §2.11: "For an exchange, the requested exchange's interval — closed on
    the left at scheduled_start_utc, open on the right at scheduled_start_utc
    + committed_minutes — is extended by a 30-minute travel buffer on both
    sides, and the resulting extended window must not overlap another
    SCHEDULED or DELIVERED exchange in which the same member participates; a
    violation is rejected with ERR_EXCHANGE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/exchange_overlap_with_30min_buffer_rejects
    """
    ctx = setup_two_members_and_offer(requester_seed=240)
    # First exchange 09:00 - 10:00
    r1 = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T09:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    get_success_data(api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r1["id"],
         "scheduled_start_utc": "2026-03-05T09:00:00Z", "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    r2 = get_success_data(api.create_skill_request(
        {"member_id": ctx["requester"]["id"], "skill_code": "GARDENING",
         "needed_minutes": 60,
         "earliest_start_utc": "2026-03-05T10:00:00Z",
         "latest_start_utc": "2026-03-05T18:00:00Z"},
        headers=make_member_headers(ctx["requester"]["id"]),
    ))
    resp = api.create_exchange(
        {"offer_id": ctx["offer"]["id"], "request_id": r2["id"],
         "scheduled_start_utc": "2026-03-05T10:25:00Z", "committed_minutes": 60},
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EXCHANGE_TIME_CONFLICT)
