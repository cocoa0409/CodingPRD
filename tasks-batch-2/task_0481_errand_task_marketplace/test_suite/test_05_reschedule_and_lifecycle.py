"""Reschedule cycle and booking-lifecycle terminal/expiry/skill transitions.

Translates difficulty queue (non_linear reschedule cycle) and corner queue
(state_machines complete-terminal, offered-expires, vet-rejected; validations no-pending).
"""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_propose_payload, create_accept_payload, create_complete_payload,
    create_skill_payload, create_fixed_category_payload,
    TEST_USERS, make_client_headers, make_tasker_headers,
    setup_catalog, create_offered_booking, create_claimed_booking,
    create_in_progress_booking, get_tasker_version, complete_booking,
)

DISP = TEST_USERS["dispatcher_headers"]
TSO = TEST_USERS["trust_safety_headers"]


def _instant(iso_str):
    """Parse an ISO 8601 UTC instant (with or without fractional digits) to a
    tz-aware datetime, so two PRD-faithful renderings of the same moment compare
    equal. PRD §2.4 mandates the server render timestamps with three fractional
    digits, so the response form differs textually from the un-normalized input."""
    s = iso_str.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def test_reschedule_cycle_returns_to_same_state(api):
    """PRD §3.6: "A booking that is CLAIMED or EN_ROUTE can have its time renegotiated through
    a propose-then-resolve cycle that leaves the booking's status unchanged".
    PRD §3.6: "On a clean accept, the booking's scheduled_start becomes the proposed_start, the
    scheduled_end is recomputed from the window duration, the reschedule_count increases by one,
    reschedule_pending clears, and the tasker's version is incremented by one."

    Design: Difficulty/non_linear_state_machine/booking_reschedule_cycle_returns_to_same_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Resched Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Rhea", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T16:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_claimed_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                estimated_hours=1.0)

    proposed_start = "2026-06-25T13:00:00Z"
    validate_success(api.propose_reschedule(
        bk["id"], create_propose_payload(proposed_start), make_client_headers(cl)), 200)

    ver = get_tasker_version(tk)
    accepted = validate_success(api.accept_reschedule(
        bk["id"], create_accept_payload(ver), make_tasker_headers(tk)), 200)

    assert accepted["status"] == "CLAIMED"
    assert accepted["reschedule_count"] == 1
    assert accepted["reschedule_pending"] is False
    # PRD §3.6: scheduled_start becomes the proposed_start. Compare as instants —
    # PRD §2.4 mandates three fractional digits, so the returned form is
    # "2026-06-25T13:00:00.000Z" while the input was "2026-06-25T13:00:00Z".
    assert _instant(accepted["scheduled_start"]) == _instant(proposed_start)


def test_complete_terminal_completed_booking_rejected(api):
    """PRD §3.3: "Any attempt to claim, depart, start, or complete from a state that does not
    permit it is rejected with ERR_BOOKING_INVALID_STATE".

    Design: Corner/state_machines/complete_terminal_completed_booking_returns_invalid_state
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Term Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "Term Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    bk = create_in_progress_booking(cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z",
                                    estimated_hours=1.0)
    complete_booking(bk["id"], tk, actual_hours=1.0)

    res = api.complete_booking(bk["id"], create_complete_payload(actual_hours=1.0),
                               make_tasker_headers(tk))
    validate_error(res, "ERR_BOOKING_INVALID_STATE")


def test_offered_booking_expires_when_clock_passes_start(api):
    """PRD §3.3: "When the logical clock reaches or passes an OFFERED booking's scheduled_start
    and no tasker has claimed it, the booking lazily transitions to EXPIRED the next time it is
    read — whether read individually or through a list."

    Design: Corner/state_machines/offered_booking_expires_when_clock_passes_start
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "Expire Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
    )
    cl = ctx["client"]["id"]
    bk = create_offered_booking(cl, ctx["category"]["id"], "2026-06-25T10:00:00Z",
                                dispatch_mode="SAME_DAY", estimated_hours=1.0)
    assert bk["status"] == "OFFERED"

    get_success_data(api.set_clock("2026-06-25T10:30:00Z", DISP))
    after = validate_success(api.get_booking(bk["id"], DISP), 200)
    assert after["status"] == "EXPIRED"


def test_vet_rejected_skill_rejected(api):
    """PRD §3.1: "a REJECTED skill is terminal and cannot be vetted again, so attempting to vet
    it fails with ERR_SKILL_INVALID_STATE."

    Design: Corner/state_machines/vet_rejected_skill_returns_skill_invalid_state
    """
    get_success_data(api.set_clock("2026-06-25T08:00:00Z", DISP))
    cat = get_success_data(api.create_category(
        create_fixed_category_payload(name="Skill Cat", fixed_price_cents=5000,
                                      default_duration_minutes=90, requires_vetting=True), DISP))
    tk = get_success_data(api.create_tasker({"full_name": "Skill Tasker", "hourly_rate_cents": 4000}, DISP))
    sk = get_success_data(api.create_skill(create_skill_payload(tk["id"], cat["id"]), DISP))
    get_success_data(api.reject_skill(sk["id"], TSO))

    res = api.vet_skill(sk["id"], TSO)
    validate_error(res, "ERR_SKILL_INVALID_STATE")


def test_reschedule_accept_without_pending_rejected(api):
    """PRD §3.6: "Accepting or declining when nothing is pending is rejected with
    ERR_NO_RESCHEDULE_PENDING."

    Design: Corner/validations/reschedule_accept_without_pending_returns_no_pending
    """
    ctx = setup_catalog(
        clock="2026-06-25T08:00:00Z",
        category_overrides={"name": "NoPend Cat", "default_hourly_rate_cents": 4000,
                            "default_duration_minutes": 60, "requires_vetting": False},
        tasker_overrides={"full_name": "NoPend Tasker", "hourly_rate_cents": 4000},
        window=("2026-06-25T09:00:00Z", "2026-06-25T14:00:00Z"),
    )
    cl, tk = ctx["client"]["id"], ctx["tasker"]["id"]
    create_claimed_booking_id = create_claimed_booking(
        cl, ctx["category"]["id"], tk, "2026-06-25T10:00:00Z", estimated_hours=1.0)["id"]

    ver = get_tasker_version(tk)
    res = api.accept_reschedule(create_claimed_booking_id, create_accept_payload(ver),
                                make_tasker_headers(tk))
    validate_error(res, "ERR_NO_RESCHEDULE_PENDING")
