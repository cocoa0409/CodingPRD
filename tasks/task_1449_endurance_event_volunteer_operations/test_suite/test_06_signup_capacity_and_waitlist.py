"""Signup capacity, waitlist routing and promotion, confirmation, and
cancellation seat handling (PRD §3.5, §3.2, §2.10).
"""
from datetime import datetime

import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    make_volunteer_headers,
    validate_success, validate_error, validate_paginated,
    set_clock,
    setup_event_with_shift, setup_published_with_volunteers,
    register_eligible_volunteer, enroll_and_pass,
    request_signup, approve_signup, confirm_signup, create_confirmed_signup,
    create_signup_payload,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Capacity boundary and the waitlist route (PRD §3.5)
# ---------------------------------------------------------------------------

def _setup_headcount_two_with_three_requests(api):
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"},
         {"full_name": "V Three", "date_of_birth": "2000-01-03"},
         {"full_name": "V Four", "date_of_birth": "2000-01-04"}],
        shift_overrides={"required_headcount": 2})
    sh = ctx["shift"]["id"]
    v1, v2, v3, v4 = ctx["volunteers"]
    sg1 = request_signup(v1["id"], sh)
    sg2 = request_signup(v2["id"], sh)
    sg3 = request_signup(v3["id"], sh)
    ctx.update({"sg1": sg1, "sg2": sg2, "sg3": sg3, "v4": v4})
    return ctx


def test_headcount_exact_fill_blocks_third_approval(api):
    """PRD §3.5: "Beyond the re-run gauntlet, approval requires spare capacity
    — the shift's `confirmed_count` still below its `required_headcount`,
    otherwise `ERR_SHIFT_CAPACITY_REACHED`."
    PRD §3.2: "when `confirmed_count` reaches `required_headcount` the shift
    flips from `OPEN` to `FULL`"

    Design: Difficulty/boundary_precision_check/headcount_exact_fill_waitlist_route
    """
    ctx = _setup_headcount_two_with_three_requests(api)
    approve_signup(ctx["sg1"]["id"])
    approve_signup(ctx["sg2"]["id"])
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["status"] == "FULL"
    assert shift["confirmed_count"] == 2 == shift["required_headcount"]
    third = api_client.approve_signup(ctx["sg3"]["id"], COORDINATOR)
    validate_error(third, ApiErrorId.ERR_SHIFT_CAPACITY_REACHED)


def test_create_at_full_routes_to_waitlist_not_error(api):
    """PRD §3.5: "The new record stamps `requested_at` with the creation
    instant and lands in `REQUESTED` status when the shift still has a free
    seat, or in `WAITLISTED` when the shift's `confirmed_count` has already
    reached its `required_headcount`; either way its `origin` begins as
    `DIRECT`, and its `is_captain` flag starts false."

    Design: Difficulty/boundary_precision_check/headcount_exact_fill_waitlist_route
    """
    ctx = _setup_headcount_two_with_three_requests(api)
    approve_signup(ctx["sg1"]["id"])
    approve_signup(ctx["sg2"]["id"])
    resp = api_client.create_signup(
        create_signup_payload(ctx["v4"]["id"], ctx["shift"]["id"]), COORDINATOR)
    sg4 = validate_success(resp, expected_status=201)
    assert sg4["status"] == "WAITLISTED", \
        "creation at full capacity routes to the waitlist; it never errors"
    assert sg4["origin"] == "DIRECT"


# ---------------------------------------------------------------------------
# The REQUESTED / WAITLISTED fork and its join on promotion (PRD §3.5)
# ---------------------------------------------------------------------------

def _setup_fork(api):
    """Headcount 1: V1 approved+confirmed (FULL); V2 (returning) WAITLISTED."""
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02", "is_returning": True}])
    v1, v2 = ctx["volunteers"]
    sg1 = create_confirmed_signup(v1["id"], ctx["shift"]["id"])
    sg2 = request_signup(v2["id"], ctx["shift"]["id"])
    ctx.update({"v1": v1, "v2": v2, "sg1": sg1, "sg2": sg2})
    return ctx


def test_waitlist_fork_requestes_vs_waitlisted(api):
    """PRD §3.5: "The new record stamps `requested_at` with the creation
    instant and lands in `REQUESTED` status when the shift still has a free
    seat, or in `WAITLISTED` when the shift's `confirmed_count` has already
    reached its `required_headcount`"
    PRD §3.2: "`confirmed_count` counts the shift's signups in `APPROVED`,
    `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` status — those are the seats
    occupied, while `REQUESTED`, `WAITLISTED`, `NO_SHOW`, and `CANCELLED`
    signups never occupy a seat."

    Design: Difficulty/non_linear_state_machine/signup_branching_waitlist_fork_join
    """
    ctx = _setup_fork(api)
    assert ctx["sg1"]["status"] == "CONFIRMED"
    assert ctx["sg2"]["status"] == "WAITLISTED", \
        "identical payloads fork on capacity alone"
    assert ctx["sg2"]["origin"] == "DIRECT"
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["confirmed_count"] == 1, "the WAITLISTED branch consumes no seat"
    assert shift["status"] == "FULL"


def test_waitlist_join_promotion_on_cancel(api):
    """PRD §3.5: "The single top candidate is promoted to `APPROVED` with
    `origin` set to `WAITLIST_PROMOTION`, `approved_at` stamped, and
    `confirm_by_at` recomputed exactly as at a manual approval; the shift's
    counts and `FULL` posture recompute the same way."

    Design: Difficulty/non_linear_state_machine/signup_branching_waitlist_fork_join
    """
    ctx = _setup_fork(api)
    validate_success(api_client.cancel_signup(
        ctx["sg1"]["id"], make_volunteer_headers(ctx["v1"]["id"])))
    promoted = validate_success(api_client.get_signup(ctx["sg2"]["id"], COORDINATOR))
    assert promoted["status"] == "APPROVED"
    assert promoted["origin"] == "WAITLIST_PROMOTION"
    assert promoted["approved_at"] is not None
    assert promoted["confirm_by_at"] is not None
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["confirmed_count"] == 1, "the seat is handed off, not lost"
    assert shift["status"] == "FULL"


# ---------------------------------------------------------------------------
# Seat conservation across a cancel/promote pair (PRD §3.2)
# ---------------------------------------------------------------------------

def _setup_seat_conservation(api):
    """Headcount 1: S1 (V1) APPROVED occupying the seat, shift FULL; S2 (V2,
    returning) WAITLISTED."""
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02", "is_returning": True}])
    v1, v2 = ctx["volunteers"]
    sg1 = request_signup(v1["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    sg2 = request_signup(v2["id"], ctx["shift"]["id"])
    assert sg2["status"] == "WAITLISTED"
    ctx.update({"v1": v1, "v2": v2, "sg1": sg1, "sg2": sg2})
    return ctx


def test_seat_conservation_cancel_promote_pair_count_stable(api):
    """PRD §3.2: "`confirmed_count` counts the shift's signups in `APPROVED`,
    `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` status — those are the seats
    occupied, while `REQUESTED`, `WAITLISTED`, `NO_SHOW`, and `CANCELLED`
    signups never occupy a seat."

    Design: Difficulty/compensating_invariant/seat_conservation_cancel_promote_pair
    """
    ctx = _setup_seat_conservation(api)
    before = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert before["confirmed_count"] == 1 and before["status"] == "FULL"
    validate_success(api_client.cancel_signup(
        ctx["sg1"]["id"], make_volunteer_headers(ctx["v1"]["id"])))
    after = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert after["confirmed_count"] == 1, \
        "the cancel (-1 seat) and its compensating promotion (+1 seat) conserve the count"
    assert after["status"] == "FULL"


def test_seat_conservation_promotion_lands_on_waitlisted(api):
    """PRD §3.5: "While the event remains `PUBLISHED`, a seat that opens on a
    shift is offered to its waitlist. Eligible candidates are the `WAITLISTED`
    signups on that shift whose volunteer is `ELIGIBLE` and who still pass the
    age, skill, training, and overlap checks at promotion time."

    Design: Difficulty/compensating_invariant/seat_conservation_cancel_promote_pair
    """
    ctx = _setup_seat_conservation(api)
    validate_success(api_client.cancel_signup(
        ctx["sg1"]["id"], make_volunteer_headers(ctx["v1"]["id"])))
    sg2 = validate_success(api_client.get_signup(ctx["sg2"]["id"], COORDINATOR))
    assert sg2["status"] == "APPROVED", "the compensating promotion lands on the waitlisted signup"
    listed, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"shift_id": ctx["shift"]["id"], "status": "APPROVED"}))
    assert meta["total_count"] == 1 and listed[0]["id"] == ctx["sg2"]["id"]


# ---------------------------------------------------------------------------
# The shift's aggregate-driven OPEN <-> FULL cycle (PRD §3.2)
# ---------------------------------------------------------------------------

def test_shift_open_full_cycle_approve_then_cancel(api):
    """PRD §3.2: "While the event is `PUBLISHED` and the shift is `OPEN` or
    `FULL`, the shift's status shadows its headcount: when `confirmed_count`
    reaches `required_headcount` the shift flips from `OPEN` to `FULL`, and
    when it drops back below, the shift returns from `FULL` to `OPEN` and the
    seat-open handling of §3.7 fires. These flips are automatic; no client
    writes the shift's status directly."

    Design: Difficulty/non_linear_state_machine/shift_compound_open_full_cycle
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"}])
    v1 = ctx["volunteers"][0]
    sg1 = request_signup(v1["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    full = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert full["status"] == "FULL" and full["confirmed_count"] == 1
    validate_success(api_client.cancel_signup(sg1["id"], make_volunteer_headers(v1["id"])))
    open_again = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert open_again["status"] == "OPEN" and open_again["confirmed_count"] == 0


def test_shift_open_full_cycle_second_leg(api):
    """PRD §3.2: "when `confirmed_count` reaches `required_headcount` the
    shift flips from `OPEN` to `FULL`, and when it drops back below, the shift
    returns from `FULL` to `OPEN`"
    PRD §3.5: "The new record stamps `requested_at` with the creation instant
    and lands in `REQUESTED` status when the shift still has a free seat"

    Design: Difficulty/non_linear_state_machine/shift_compound_open_full_cycle
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"}])
    v1, v2 = ctx["volunteers"]
    sg1 = request_signup(v1["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    validate_success(api_client.cancel_signup(sg1["id"], make_volunteer_headers(v1["id"])))
    sg2 = request_signup(v2["id"], ctx["shift"]["id"])
    assert sg2["status"] == "REQUESTED", "with the seat free again, creation forks REQUESTED"
    approve_signup(sg2["id"])
    full_again = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert full_again["status"] == "FULL" and full_again["confirmed_count"] == 1


# ---------------------------------------------------------------------------
# Priority: state gate beats safety gate on approve (PRD §2.10)
# ---------------------------------------------------------------------------

def _setup_cancelled_signup_with_expired_training(api):
    """V1 passed SAFETY_BRIEFING at 2026-08-20 (valid thirty days) and is
    CONFIRMED on a training-gated shift; the 2026-09-20 sweep expires the
    record and cascades the signup to CANCELLED."""
    ctx = setup_event_with_shift(
        publish=True,
        role_overrides={"required_training_module": "SAFETY_BRIEFING"},
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T08:00:00Z",
                         "required_headcount": 2})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    rec = enroll_and_pass(ev, vol["id"], "SAFETY_BRIEFING")
    sg = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
    set_clock("2026-09-20T00:00:00Z")
    validate_success(api_client.run_epoch_sweep(ev, DIRECTOR))
    ctx.update({"vol": vol, "rec": rec, "sg": sg})
    return ctx


def test_approve_state_beats_safety_on_cancelled_signup(api):
    """PRD §2.10: "4. State preconditions: the state-machine gates of the
    target resources — event status gates, signup status gates, and the
    training, role-entry, group, hour-log, distribution, debrief, and
    adjustment state checks"
    PRD §2.10: "7. Training currency (`ERR_TRAINING_NOT_CURRENT`)."
    PRD §3.5: "Approval is a coordinator action on a `REQUESTED` signup; from
    any other status the request fails with `ERR_SIGNUP_NOT_APPROVABLE`."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_safety_on_cancelled_signup
    """
    ctx = _setup_cancelled_signup_with_expired_training(api)
    rec = validate_success(api_client.get_training_record(ctx["rec"]["id"], COORDINATOR))
    assert rec["status"] == "EXPIRED", "the safety check would also fail"
    sg = validate_success(api_client.get_signup(ctx["sg"]["id"], COORDINATOR))
    assert sg["status"] == "CANCELLED", "the state check fails first"
    resp = api_client.approve_signup(ctx["sg"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_APPROVABLE)


def test_approve_cancelled_signup_stably_rejected(api):
    """PRD §3.5: "Approval is a coordinator action on a `REQUESTED` signup;
    from any other status the request fails with `ERR_SIGNUP_NOT_APPROVABLE`."
    PRD §2.10: "A request that would fail several checks is answered with
    exactly one error, and which error is not arbitrary."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_beats_safety_on_cancelled_signup
    """
    ctx = _setup_cancelled_signup_with_expired_training(api)
    first = api_client.approve_signup(ctx["sg"]["id"], COORDINATOR)
    validate_error(first, ApiErrorId.ERR_SIGNUP_NOT_APPROVABLE)
    second = api_client.approve_signup(ctx["sg"]["id"], COORDINATOR)
    validate_error(second, ApiErrorId.ERR_SIGNUP_NOT_APPROVABLE)
    sg = validate_success(api_client.get_signup(ctx["sg"]["id"], COORDINATOR))
    assert sg["status"] == "CANCELLED", "CANCELLED is terminal; repeated approves change nothing"


# ---------------------------------------------------------------------------
# Event-state gate on signup creation (PRD §3.5)
# ---------------------------------------------------------------------------

def _setup_locked_event(api):
    ctx = setup_event_with_shift(publish=True)
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    validate_success(api_client.lock_signups(ev, DIRECTOR))
    ctx["vol"] = vol
    return ctx


def test_signup_create_gated_by_event_state_rejected(api):
    """PRD §3.5: "The event must be `PUBLISHED` (`ERR_EVENT_NOT_PUBLISHED`);
    the volunteer must be `ELIGIBLE` (`ERR_VOLUNTEER_NOT_ELIGIBLE`); the shift
    must be `OPEN` or `FULL` — a `LOCKED`, `IN_PROGRESS`, `RECONCILED`, or
    `CANCELLED` shift rejects with `ERR_SHIFT_NOT_OPEN`"

    Design: Difficulty/cross_entity_state_dependency/signup_create_gated_by_event_state
    """
    ctx = _setup_locked_event(api)
    resp = api_client.create_signup(
        create_signup_payload(ctx["vol"]["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED)


def test_signup_create_gated_by_event_state_shift_locked(api):
    """PRD §3.1: "Either way the event moves from `PUBLISHED` to `LOCKED`,
    and every shift of the event in `OPEN` or `FULL` status cascades to
    `LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/signup_create_gated_by_event_state
    """
    ctx = _setup_locked_event(api)
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["status"] == "LOCKED", "the event lock cascades to its shifts"
    resp = api_client.create_signup(
        create_signup_payload(ctx["vol"]["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED)
    listed, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"shift_id": ctx["shift"]["id"]}))
    assert meta["total_count"] == 0, "no signup row may be persisted for a locked event"


# ---------------------------------------------------------------------------
# Confirmation gates and deadline (PRD §3.5)
# ---------------------------------------------------------------------------

def test_confirm_from_requested_rejected(api):
    """PRD §3.5: "the signup must be `APPROVED` (`ERR_SIGNUP_NOT_CONFIRMABLE`)"

    Design: Corner/state_machines/confirm_from_requested_rejected
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"required_headcount": 2})
    vol = ctx["volunteers"][0]
    sg = request_signup(vol["id"], ctx["shift"]["id"])
    resp = api_client.confirm_signup(sg["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_CONFIRMABLE)
    after = validate_success(api_client.get_signup(sg["id"], COORDINATOR))
    assert after["status"] == "REQUESTED"


def test_confirm_after_deadline_rejected(api):
    """PRD §3.5: "A successful approval moves the signup to `APPROVED`, stamps
    `approved_at`, and computes `confirm_by_at` as the earlier of two
    instants: forty-eight hours after `approved_at`, or one hour before the
    shift's `start_at`."
    PRD §3.5: "the logical clock must not have passed `confirm_by_at`
    (`ERR_CONFIRM_DEADLINE_PASSED`)"

    Design: Corner/state_machines/confirm_after_deadline_rejected
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}])
    vol = ctx["volunteers"][0]
    sg = request_signup(vol["id"], ctx["shift"]["id"])
    approved = approve_signup(sg["id"])
    assert _parse_ts(approved["confirm_by_at"]) == _parse_ts("2026-08-22T00:00:00Z"), \
        "approved at 2026-08-20T00:00:00Z, forty-eight hours out is the earlier instant"
    set_clock("2026-08-23T00:00:00Z")
    resp = api_client.confirm_signup(sg["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_CONFIRM_DEADLINE_PASSED)


def test_terminal_cancelled_signup_rejects_approve(api):
    """PRD §3.5: "Approval is a coordinator action on a `REQUESTED` signup;
    from any other status the request fails with `ERR_SIGNUP_NOT_APPROVABLE`."
    PRD §3.5: "cancellation from `CHECKED_IN`, `COMPLETED`, `NO_SHOW`, or
    `CANCELLED` is rejected with `ERR_SIGNUP_NOT_CANCELLABLE`"

    Design: Corner/state_machines/terminal_cancelled_signup_rejects_approve
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"required_headcount": 2})
    vol = ctx["volunteers"][0]
    sg = request_signup(vol["id"], ctx["shift"]["id"])
    validate_success(api_client.cancel_signup(sg["id"], make_volunteer_headers(vol["id"])))
    approve_resp = api_client.approve_signup(sg["id"], COORDINATOR)
    validate_error(approve_resp, ApiErrorId.ERR_SIGNUP_NOT_APPROVABLE)
    cancel_resp = api_client.cancel_signup(sg["id"], COORDINATOR)
    validate_error(cancel_resp, ApiErrorId.ERR_SIGNUP_NOT_CANCELLABLE)


# ---------------------------------------------------------------------------
# Immediate consistency of derived counters (PRD §2.5, §3.2)
# ---------------------------------------------------------------------------

def test_writes_visible_immediately_in_same_response(api):
    """PRD §3.5: "The new record stamps `requested_at` with the creation
    instant and lands in `REQUESTED` status when the shift still has a free
    seat, or in `WAITLISTED` when the shift's `confirmed_count` has already
    reached its `required_headcount`; either way its `origin` begins as
    `DIRECT`, and its `is_captain` flag starts false."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/writes_visible_immediately_in_same_response
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}])
    vol = ctx["volunteers"][0]
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    sg = validate_success(resp, expected_status=201)
    assert sg["status"] == "REQUESTED"
    assert sg["origin"] == "DIRECT"
    assert sg["requested_at"] is not None
    assert sg["is_captain"] is False
    fetched = validate_success(api_client.get_signup(sg["id"], COORDINATOR))
    assert fetched["status"] == "REQUESTED"


def test_derived_counts_reconcile_immediately_on_cancel(api):
    """PRD §3.2: "The counters recompute on every signup approval, promotion,
    backfill, cancellation, no-show, sweep timeout, check-in, and check-out."
    PRD §2.5: "Any mutation — client-driven or system-driven — refreshes the
    affected resource's `updated_at` timestamp and increments its `version`."

    Design: Corner/complexity_layers/derived_counts_reconcile_immediately_on_cancel
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}])
    vol = ctx["volunteers"][0]
    sg = request_signup(vol["id"], ctx["shift"]["id"])
    approve_signup(sg["id"])
    before = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert before["status"] == "FULL" and before["confirmed_count"] == 1
    validate_success(api_client.cancel_signup(sg["id"], make_volunteer_headers(vol["id"])))
    after = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert after["confirmed_count"] == 0, "the very next read shows the freed seat"
    assert after["status"] == "OPEN"
    assert after["version"] > before["version"], \
        "the cascade-driven shift mutation increments its version"


# ---------------------------------------------------------------------------
# Manual shift cancellation (PRD §3.2)
# ---------------------------------------------------------------------------

def test_signup_against_cancelled_shift_rejected(api):
    """PRD §3.2: "A coordinator may decommission an `OPEN` or `FULL` shift
    while its event is `DRAFT` or `PUBLISHED`; from any other event state the
    manual cancellation is rejected with `ERR_INVALID_EVENT_STATE`. The shift
    becomes `CANCELLED`, and every signup on it in `REQUESTED`, `WAITLISTED`,
    `APPROVED`, or `CONFIRMED` status is cancelled with it."
    PRD §3.5: "the shift must be `OPEN` or `FULL` — a `LOCKED`, `IN_PROGRESS`,
    `RECONCILED`, or `CANCELLED` shift rejects with `ERR_SHIFT_NOT_OPEN`"

    Design: Corner/errors/signup_against_cancelled_shift_rejected
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"}],
        shift_overrides={"required_headcount": 2})
    v1, v2 = ctx["volunteers"]
    sg1 = request_signup(v1["id"], ctx["shift"]["id"])
    cancelled = validate_success(api_client.cancel_shift(ctx["shift"]["id"], COORDINATOR))
    assert cancelled["status"] == "CANCELLED"
    sg1_after = validate_success(api_client.get_signup(sg1["id"], COORDINATOR))
    assert sg1_after["status"] == "CANCELLED", "the shift cancel cascades to its signups"
    resp = api_client.create_signup(
        create_signup_payload(v2["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)


# ---------------------------------------------------------------------------
# Signup listing by status (PRD §2.3)
# ---------------------------------------------------------------------------

def test_signup_list_filtered_by_status(api):
    """PRD §2.3: "signups filter by `event_id`, `volunteer_id`, `shift_id`,
    `status`, or `replaces_signup_id`"

    Design: Corner/endpoints/signup_list_filtered_by_status
    """
    ctx = setup_published_with_volunteers(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"}])
    v1, v2 = ctx["volunteers"]
    sg1 = request_signup(v1["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    sg2 = request_signup(v2["id"], ctx["shift"]["id"])
    assert sg2["status"] == "WAITLISTED"
    data, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"shift_id": ctx["shift"]["id"], "status": "WAITLISTED"}))
    assert meta["total_count"] == 1
    assert [s["id"] for s in data] == [sg2["id"]]
