"""Trip lifecycle: DRAFT → SUBMITTED → APPROVED / REJECTED / CHANGES_REQUESTED
→ COMPLETED / CANCELLED, plus per-diem-window submission gating.

Covers PRD §3.1 (Trip), §2.4 (version increment), §2.7 priority
ordering for state vs cross-entity-state.
"""
from __future__ import annotations

import uuid

import pytest

from test_helpers import (
    assert_trip,
    assert_version_incremented_by,
    create_draft_trip,
    create_trip_payload,
    make_traveler_headers,
    seed_default_boston_rate,
    seed_manager,
    seed_traveler,
    setup_approved_trip,
    setup_draft_trip,
    setup_submitted_trip,
    submit_trip,
    approve_trip,
    reject_trip,
    request_changes_trip,
    cancel_trip,
    clock_advance,
    validate_error,
    validate_success,
)


# ===========================================================================
# Create + retrieve
# ===========================================================================
def test_create_trip_returns_draft(api):
    """PRD §3.1: "The trip is born in `DRAFT` with its `status` field
    set accordingly and with `estimated_budget_cents` initialized to
    zero and `pinned_per_diem_rate_id` and `approved_at` both null."
    """
    manager = seed_manager()
    traveler = seed_traveler(manager_id=manager["id"])
    seed_default_boston_rate()
    res = api.create_trip(
        create_trip_payload(traveler_id=traveler["id"]),
        make_traveler_headers(traveler["id"]),
    )
    trip = validate_success(res, 201)
    assert_trip(trip)
    assert trip["status"] == "DRAFT"
    assert trip["estimated_budget_cents"] == 0
    assert trip["pinned_per_diem_rate_id"] is None
    assert trip["approved_at"] is None


def test_create_trip_with_end_before_start_rejected(api):
    """PRD §3.1: "`end_date` must be greater than or equal to
    `start_date`"."""
    manager = seed_manager()
    traveler = seed_traveler(manager_id=manager["id"])
    payload = create_trip_payload(
        traveler_id=traveler["id"],
        start_date="2025-06-10T00:00:00.000Z",
        end_date="2025-06-05T00:00:00.000Z",
    )
    res = api.create_trip(payload, make_traveler_headers(traveler["id"]))
    assert 400 <= res.status_code < 500, res.text


# ===========================================================================
# DRAFT → SUBMITTED
# ===========================================================================
def test_submit_trip_transitions_to_submitted_and_sets_budget(api):
    """PRD §3.1: "submitting the trip advances `status` from `DRAFT` to
    `SUBMITTED` ... As a side effect of successful submission, the
    server computes the provisional `estimated_budget_cents`"
    """
    cast = setup_draft_trip()
    old_version = cast["trip"]["version"]
    res = api.submit_trip(
        cast["trip"]["id"], make_traveler_headers(cast["traveler"]["id"]),
    )
    trip = validate_success(res, 200)
    assert trip["status"] == "SUBMITTED"
    assert trip["estimated_budget_cents"] > 0
    assert_version_incremented_by(trip["version"], old_version, 1)


def test_submit_trip_by_non_owner_rejected(api):
    """PRD §3.1: "Submission is only valid when the traveler issuing the
    request owns the trip (the trip's `traveler_id` equals the calling
    `X-User-ID`)".
    """
    cast = setup_draft_trip()
    other_manager = seed_manager()
    other_traveler = seed_traveler(manager_id=other_manager["id"])
    res = api.submit_trip(
        cast["trip"]["id"],
        make_traveler_headers(other_traveler["id"]),
    )
    # PRD §3.1 doesn't pin a specific error_id for the non-owner case
    # on /submit; accept the segregation/forbidden family or generic.
    assert 400 <= res.status_code < 500, res.text


def test_submit_trip_with_destination_without_rate_returns_per_diem_unavailable(
    api,
):
    """PRD §3.1: "If no such rate row exists, submission fails with
    `ERR_PER_DIEM_UNAVAILABLE`."
    """
    manager = seed_manager()
    traveler = seed_traveler(manager_id=manager["id"])
    # No PerDiemRate for "Nowhere, ZZ".
    res = api.create_trip(
        create_trip_payload(
            traveler_id=traveler["id"],
            destination_city=f"Nowhere-{uuid.uuid4().hex[:6]}",
            destination_state="ZZ",
        ),
        make_traveler_headers(traveler["id"]),
    )
    trip = validate_success(res, 201)
    sub = api.submit_trip(
        trip["id"], make_traveler_headers(traveler["id"]),
    )
    validate_error(sub, "ERR_PER_DIEM_UNAVAILABLE")


# ===========================================================================
# SUBMITTED → APPROVED (with pinning side-effect)
# ===========================================================================
def test_approve_trip_pins_rate_and_sets_approved_at(api):
    """PRD §3.1: "Approval advances `status` from `SUBMITTED` to
    `APPROVED`, pins `pinned_per_diem_rate_id` to the `id` of the
    `PerDiemRate` that was resolved at submission (defending against
    subsequent administrative edits), and stamps `approved_at` with the
    current server time."
    """
    cast = setup_submitted_trip()
    res = api.approve_trip(
        cast["trip"]["id"], make_traveler_headers(cast["traveler"]["id"])
        if False else __import__("test_helpers").make_manager_headers(
            cast["manager"]["id"]
        ),
    )
    trip = validate_success(res, 200)
    assert trip["status"] == "APPROVED"
    assert trip["pinned_per_diem_rate_id"] == cast["rate"]["id"]
    assert trip["approved_at"] is not None


def test_approve_trip_by_non_manager_rejected(api):
    """PRD §3.1: "The manager — whose `Employee.id` must equal the
    traveler's `manager_id` — may take one of three actions."
    """
    from test_helpers import make_manager_headers
    cast = setup_submitted_trip()
    other_manager = seed_manager()
    res = api.approve_trip(
        cast["trip"]["id"], make_manager_headers(other_manager["id"]),
    )
    assert 400 <= res.status_code < 500, res.text


# ===========================================================================
# SUBMITTED → REJECTED + cascades
# ===========================================================================
def test_reject_trip_transitions_to_rejected_terminal(api):
    """PRD §3.1: "Rejection advances `status` from `SUBMITTED` to
    `REJECTED` (a terminal state)".
    """
    from test_helpers import make_manager_headers
    cast = setup_submitted_trip()
    res = api.reject_trip(
        cast["trip"]["id"], make_manager_headers(cast["manager"]["id"]),
    )
    trip = validate_success(res, 200)
    assert trip["status"] == "REJECTED"


# ===========================================================================
# SUBMITTED → CHANGES_REQUESTED → DRAFT (cycle)
# ===========================================================================
def test_request_changes_then_patch_returns_to_draft(api):
    """PRD §3.1: "A `CHANGES_REQUESTED` trip cycles back to `DRAFT` the
    next time the traveler edits the trip; the transition clears
    `estimated_budget_cents` back to zero and clears
    `pinned_per_diem_rate_id` back to null".
    """
    from test_helpers import make_manager_headers, update_trip_payload
    cast = setup_submitted_trip()
    res = api.request_changes_trip(
        cast["trip"]["id"], make_manager_headers(cast["manager"]["id"]),
    )
    cr_trip = validate_success(res, 200)
    assert cr_trip["status"] == "CHANGES_REQUESTED"

    # Now traveler PATCHes — should cycle back to DRAFT and clear budget.
    patch = update_trip_payload(
        version=cr_trip["version"], purpose="updated purpose",
    )
    res2 = api.update_trip(
        cr_trip["id"], patch,
        make_traveler_headers(cast["traveler"]["id"]),
    )
    edited = validate_success(res2, 200)
    assert edited["status"] == "DRAFT"
    assert edited["estimated_budget_cents"] == 0
    assert edited["pinned_per_diem_rate_id"] is None


# ===========================================================================
# APPROVED → COMPLETED (clock-gated)
# ===========================================================================
def test_complete_trip_before_end_date_rejected(api):
    """PRD §3.1: "The traveler may complete the trip — provided the
    current logical date is on or after `end_date` — which advances
    `status` to `COMPLETED` (terminal)."

    Negative case: before end_date, /complete must fail.
    """
    cast = setup_approved_trip()
    res = api.complete_trip(
        cast["trip"]["id"],
        make_traveler_headers(cast["traveler"]["id"]),
    )
    # PRD doesn't pin the exact error_id for "before end_date"; assert
    # only that the request is rejected.
    assert 400 <= res.status_code < 500, res.text


def test_complete_trip_after_clock_advance_succeeds(api):
    """PRD §3.1 / §3.12: "Completion is gated on the server's logical
    clock, which an admin-only test-driving capability can advance to a
    supplied `to` instant."
    """
    from test_helpers import add_days
    cast = setup_approved_trip()
    clock_advance(to_iso=add_days(cast["trip"]["end_date"], 1))
    res = api.complete_trip(
        cast["trip"]["id"],
        make_traveler_headers(cast["traveler"]["id"]),
    )
    trip = validate_success(res, 200)
    assert trip["status"] == "COMPLETED"


# ===========================================================================
# APPROVED → CANCELLED
# ===========================================================================
def test_cancel_approved_trip_transitions_to_cancelled(api):
    """PRD §3.1: "the traveler may cancel the trip — provided no
    `ExpenseReport` on this trip has a `status` other than `DRAFT` —
    which advances `status` to `CANCELLED` (terminal)".
    """
    cast = setup_approved_trip()
    res = api.cancel_trip(
        cast["trip"]["id"],
        make_traveler_headers(cast["traveler"]["id"]),
    )
    trip = validate_success(res, 200)
    assert trip["status"] == "CANCELLED"


# ===========================================================================
# Invalid transitions
# ===========================================================================
@pytest.mark.parametrize("action_name", [
    "approve_trip",
    "reject_trip",
    "request_changes_trip",
    "cancel_trip",
])
def test_action_on_draft_trip_when_inappropriate_rejected(api, action_name):
    """PRD §2.7 #5: "the resource being in a state that permits the
    requested transition, returning `ERR_INVALID_STATE`".

    /approve, /reject, /request-changes, /cancel from DRAFT are not
    valid per PRD §3.1. (Submit IS valid from DRAFT and is exercised
    by its own positive test.)
    """
    from test_helpers import make_manager_headers
    cast = setup_draft_trip()
    actor_headers = (
        make_traveler_headers(cast["traveler"]["id"])
        if action_name in ("cancel_trip",)
        else make_manager_headers(cast["manager"]["id"])
    )
    method = getattr(api, action_name)
    res = method(cast["trip"]["id"], actor_headers)
    validate_error(res, "ERR_INVALID_STATE")
