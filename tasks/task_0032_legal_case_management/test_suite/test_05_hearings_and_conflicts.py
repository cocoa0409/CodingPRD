"""Hearing scheduling: temporal sanity, court-room overlap, lead-lawyer
travel buffer, prep-task generation, and rescheduling.

PRD §2.7 + §3.4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    add_minutes,
    add_hours,
    advance_clock,
    api_client,
    assert_hearing,
    create_hearing_payload,
    make_partner_lawyer,
    register_case,
    setup_three_lawyers_and_active_case,
    setup_partner_and_active_case,
    setup_hearing_baseline,
    add_verified_party,
    activate_case,
    schedule_hearing,
    unique_court_room,
    validate_error,
    validate_success,
)


BASE_TS = "2026-06-01T08:00:00.000Z"


# ---------------------------------------------------------------------------
# Temporal sanity
# ---------------------------------------------------------------------------
def test_end_must_be_after_start(api):
    """PRD §3.4: 'Both timestamps are ISO 8601 UTC; scheduled_end must be
    strictly greater than scheduled_start (rejected as
    ERR_HEARING_INVALID_INTERVAL).'
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    payload = create_hearing_payload(
        case_id=bundle["case"]["id"],
        scheduled_start=add_hours(BASE_TS, 5),
        scheduled_end=add_hours(BASE_TS, 5),  # equal → invalid
    )
    res = api.create_hearing(payload, bundle["partner_headers"])
    validate_error(res, "ERR_HEARING_INVALID_INTERVAL",
                   expected_status=422)


def test_past_start_time_rejected(api):
    """PRD §3.4: 'scheduled_start must be strictly greater than the
    current server time (rejected as ERR_HEARING_PAST_TIME).'
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    payload = create_hearing_payload(
        case_id=bundle["case"]["id"],
        scheduled_start=add_hours(BASE_TS, -2),
        scheduled_end=add_hours(BASE_TS, -1),
    )
    res = api.create_hearing(payload, bundle["partner_headers"])
    validate_error(res, "ERR_HEARING_PAST_TIME", expected_status=422)


# ---------------------------------------------------------------------------
# Court-room overlap (half-open) — see also difficulty test 10
# ---------------------------------------------------------------------------
def test_room_touching_is_allowed(api):
    """PRD §2.7: 'Court-room capacity is governed by half-open intervals:
    two SCHEDULED hearings sharing the same court_room may not have
    overlapping [scheduled_start, scheduled_end) windows, but a hearing
    whose scheduled_start equals the previous hearing's scheduled_end is
    allowed (touching does not overlap).'

    Note: To exercise the ROOM rule alone, the two hearings must have
    DIFFERENT lead lawyers — otherwise the stricter PRD §2.7 lead-lawyer
    30-minute travel buffer would reject touching at boundary.
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    room = unique_court_room("ROOM-TOUCH")
    schedule_hearing(
        case_id=bundle["case"]["id"],
        actor_headers=bundle["partner_headers"],
        scheduled_start=add_hours(BASE_TS, 2),
        scheduled_end=add_hours(BASE_TS, 4),
        court_room=room,
    )
    # Build a second case with a DIFFERENT lead lawyer so the lawyer
    # buffer rule doesn't shadow the room-touching rule.
    partner2, partner2_headers = make_partner_lawyer(
        bootstrap_partner_headers=bundle["partner_headers"],
    )
    case2 = register_case(
        lead_lawyer_id=partner2["id"], actor_headers=partner2_headers,
        case_type="CIVIL", claim_amount_cents=5_000_000,
    )
    add_verified_party(case_id=case2["id"], party_role="PLAINTIFF",
                       actor_headers=partner2_headers)
    add_verified_party(case_id=case2["id"], party_role="DEFENDANT",
                       actor_headers=partner2_headers)
    case2 = activate_case(case2["id"], partner2_headers)
    res = api.create_hearing(
        create_hearing_payload(
            case_id=case2["id"],
            court_room=room,
            scheduled_start=add_hours(BASE_TS, 4),  # exactly touching
            scheduled_end=add_hours(BASE_TS, 6),
        ),
        partner2_headers,
    )
    validate_success(res, 201)


def test_room_overlap_rejected(api):
    """PRD §2.7: 'two SCHEDULED hearings sharing the same court_room may
    not have overlapping [scheduled_start, scheduled_end) windows ...
    Violations surface ERR_HEARING_ROOM_CONFLICT.'
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    room = unique_court_room("ROOM-OVERLAP")
    schedule_hearing(
        case_id=bundle["case"]["id"],
        actor_headers=bundle["partner_headers"],
        scheduled_start=add_hours(BASE_TS, 2),
        scheduled_end=add_hours(BASE_TS, 4),
        court_room=room,
    )
    # Build a second case with a different lead lawyer so the room
    # check fires before the lead-lawyer buffer (the impl evaluates room
    # conflict at priority 13 before lawyer conflict at priority 14, but
    # using a different partner makes the test resilient regardless).
    partner2, partner2_headers = make_partner_lawyer(
        bootstrap_partner_headers=bundle["partner_headers"],
    )
    case2 = register_case(
        lead_lawyer_id=partner2["id"], actor_headers=partner2_headers,
        case_type="CIVIL", claim_amount_cents=5_000_000,
    )
    add_verified_party(case_id=case2["id"], party_role="PLAINTIFF",
                       actor_headers=partner2_headers)
    add_verified_party(case_id=case2["id"], party_role="DEFENDANT",
                       actor_headers=partner2_headers)
    case2 = activate_case(case2["id"], partner2_headers)
    res = api.create_hearing(
        create_hearing_payload(
            case_id=case2["id"],
            court_room=room,
            scheduled_start=add_hours(BASE_TS, 3),
            scheduled_end=add_hours(BASE_TS, 5),
        ),
        partner2_headers,
    )
    validate_error(res, "ERR_HEARING_ROOM_CONFLICT", expected_status=409)


# ---------------------------------------------------------------------------
# Lead-lawyer 30-minute travel buffer (cross-case)
# ---------------------------------------------------------------------------
def test_lawyer_buffer_violation_rejected(api):
    """PRD §2.7: 'Lead-lawyer capacity is stricter: two SCHEDULED hearings
    that share the same lead_lawyer_id — even across different cases and
    different rooms — must be separated by a 30-minute travel buffer, so
    the next hearing's scheduled_start must be greater than or equal to
    the previous hearing's scheduled_end plus 30 minutes. Violations
    surface ERR_LAWYER_SCHEDULE_CONFLICT.'
    """
    partner, partner_headers, case_a = setup_partner_and_active_case()
    # Build a second case with the same lead lawyer.
    case_b = register_case(
        lead_lawyer_id=partner["id"], actor_headers=partner_headers,
        case_type="CIVIL", claim_amount_cents=5_000_000,
    )
    add_verified_party(case_id=case_b["id"], party_role="PLAINTIFF",
                       actor_headers=partner_headers)
    add_verified_party(case_id=case_b["id"], party_role="DEFENDANT",
                       actor_headers=partner_headers)
    case_b = activate_case(case_b["id"], partner_headers)
    advance_clock(BASE_TS)
    room_a = unique_court_room("ROOM-LB-A")
    room_b = unique_court_room("ROOM-LB-B")
    schedule_hearing(
        case_id=case_a["id"], actor_headers=partner_headers,
        scheduled_start=add_hours(BASE_TS, 2),
        scheduled_end=add_hours(BASE_TS, 4),
        court_room=room_a,
    )
    # Touching at boundary in another room — buffer violation.
    res = api.create_hearing(
        create_hearing_payload(
            case_id=case_b["id"], court_room=room_b,
            scheduled_start=add_hours(BASE_TS, 4),
            scheduled_end=add_hours(BASE_TS, 5),
        ),
        partner_headers,
    )
    validate_error(res, "ERR_LAWYER_SCHEDULE_CONFLICT", expected_status=409)


def test_lawyer_buffer_at_exactly_30_min_accepted(api):
    """PRD §2.7: 'next hearing's scheduled_start must be greater than or
    equal to the previous hearing's scheduled_end plus 30 minutes.'

    Claim: scheduled_start == prev.end + 30 min satisfies the buffer
    (greater-than-or-equal).
    """
    partner, partner_headers, case_a = setup_partner_and_active_case()
    case_b = register_case(
        lead_lawyer_id=partner["id"], actor_headers=partner_headers,
        case_type="CIVIL", claim_amount_cents=5_000_000,
    )
    add_verified_party(case_id=case_b["id"], party_role="PLAINTIFF",
                       actor_headers=partner_headers)
    add_verified_party(case_id=case_b["id"], party_role="DEFENDANT",
                       actor_headers=partner_headers)
    case_b = activate_case(case_b["id"], partner_headers)
    advance_clock(BASE_TS)
    room_a = unique_court_room("ROOM-LB30-A")
    room_b = unique_court_room("ROOM-LB30-B")
    schedule_hearing(
        case_id=case_a["id"], actor_headers=partner_headers,
        scheduled_start=add_hours(BASE_TS, 2),
        scheduled_end=add_hours(BASE_TS, 4),
        court_room=room_a,
    )
    new_start = add_minutes(add_hours(BASE_TS, 4), 30)
    res = api.create_hearing(
        create_hearing_payload(
            case_id=case_b["id"], court_room=room_b,
            scheduled_start=new_start,
            scheduled_end=add_minutes(new_start, 60),
        ),
        partner_headers,
    )
    validate_success(res, 201)


# ---------------------------------------------------------------------------
# Prep tasks
# ---------------------------------------------------------------------------
def test_prep_tasks_generated_on_scheduling(api):
    """PRD §3.4: 'On successful scheduling, the system generates a
    deterministic prep-task checklist as a side effect and sets
    prep_tasks_generated to true.'
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    h = schedule_hearing(
        case_id=bundle["case"]["id"],
        actor_headers=bundle["partner_headers"],
        scheduled_start=add_hours(BASE_TS, 5),
        scheduled_end=add_hours(BASE_TS, 6),
    )
    assert h["prep_tasks_generated"] is True


def test_prep_tasks_listed_via_get(api):
    """PRD §3.4: 'Reading the prep-task checklist returns the same
    deterministic list.' PRD §3.4 also says the checklist always begins
    with a confirmation task for court_room and arrival time.
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    h = schedule_hearing(
        case_id=bundle["case"]["id"],
        actor_headers=bundle["partner_headers"],
        scheduled_start=add_hours(BASE_TS, 5),
        scheduled_end=add_hours(BASE_TS, 6),
    )
    res = api.get_prep_tasks(h["id"], bundle["partner_headers"])
    body = validate_success(res, 200)
    # PRD §3.4 names the checklist a "list" but does not pin the JSON key.
    # Accept either an array directly or any list-typed value under common
    # keys ("tasks", "prep_tasks", "checklist").
    tasks = None
    if isinstance(body, list):
        tasks = body
    elif isinstance(body, dict):
        for k in ("tasks", "prep_tasks", "checklist"):
            if isinstance(body.get(k), list):
                tasks = body[k]
                break
    assert isinstance(tasks, list)
    assert len(tasks) >= 1


# ---------------------------------------------------------------------------
# Cancel cascade from case hold
# ---------------------------------------------------------------------------
def test_case_hold_cancels_scheduled_hearings(api):
    """PRD §2.9: 'When a case transitions from ACTIVE to ON_HOLD, every
    Hearing row on the case whose status is SCHEDULED is moved to
    CANCELLED and the case posture is recomputed.'
    """
    bundle = setup_hearing_baseline(base_ts=BASE_TS)
    h = schedule_hearing(
        case_id=bundle["case"]["id"],
        actor_headers=bundle["partner_headers"],
        scheduled_start=add_hours(BASE_TS, 100),
        scheduled_end=add_hours(BASE_TS, 102),
    )
    case_after = validate_success(
        api.hold_case(bundle["case"]["id"], bundle["partner_headers"]), 200
    )
    assert case_after["status"] == "ON_HOLD"
    # Hearing should be CANCELLED.
    after = validate_success(
        api.list_case_hearings(bundle["case"]["id"],
                               bundle["partner_headers"]), 200,
    )
    # validate_paginated would also work; list endpoint uses paginated envelope.
    if isinstance(after, list):
        ids = [r for r in after if r["id"] == h["id"]]
    else:
        ids = []
    # Re-fetch via the list endpoint with paginated envelope.
    from test_helpers import validate_paginated
    data, _ = validate_paginated(api.list_case_hearings(
        bundle["case"]["id"], bundle["partner_headers"]
    ))
    matching = [r for r in data if r["id"] == h["id"]]
    assert matching and matching[0]["status"] == "CANCELLED"
