"""Trip-request submission, approval routing, revision loop, and rank/state gates."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_policy, make_traveler, make_vendor, make_rate, make_trip,
    submit_trip, approve_trip, reject_trip, trip_version, set_clock,
    make_traveler_headers, make_approver_headers,
    create_booking_payload,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_DEFAULT

MGR = TEST_USERS["travel_manager_headers"]


def _pending_manager_trip(market_estimate=200000, traveler_grade="STANDARD"):
    """Trip submitted to PENDING_MANAGER (market estimate in the MANAGER band)."""
    policy = make_policy()
    traveler = make_traveler(policy["id"], grade=traveler_grade)
    approver = make_traveler(policy["id"], grade="MANAGER")
    trip = make_trip(traveler["id"], market_estimate_cents=market_estimate)
    trip = submit_trip(trip["id"], traveler["id"])
    return {"policy": policy, "traveler": traveler, "approver": approver, "trip": trip}


# ─── Revision loop (cyclic state machine) ─────────────
def test_reject_returns_pending_trip_to_draft(api):
    """PRD §3.2: "an approver ... may reject a trip that is in either `PENDING_MANAGER`
    or `PENDING_EXEC`, optionally supplying a `reason`; rejection returns the trip to
    `DRAFT` so the traveler can revise and resubmit."

    Design: Difficulty/non_linear_state_machine/trip_request_reject_revision_loop_cycle
    """
    ctx = _pending_manager_trip()
    assert ctx["trip"]["status"] == "PENDING_MANAGER"
    rejected = reject_trip(ctx["trip"]["id"], ctx["approver"]["id"], reason="adjust dates")
    assert rejected["status"] == "DRAFT", f"reject should return trip to DRAFT, got {rejected['status']}"


def test_reject_then_resubmit_reenters_pending_manager(api):
    """PRD §3.2: "rejection returns the trip to `DRAFT` so the traveler can revise and
    resubmit."
    PRD §3.2: "When the level is `MANAGER` or `EXEC`, submission moves the trip to
    `PENDING_MANAGER`."

    Design: Difficulty/non_linear_state_machine/trip_request_reject_revision_loop_cycle
    """
    ctx = _pending_manager_trip()
    trav, appr, trip = ctx["traveler"], ctx["approver"], ctx["trip"]
    reject_trip(trip["id"], appr["id"], reason="adjust dates")
    resubmitted = submit_trip(trip["id"], trav["id"])
    assert resubmitted["status"] == "PENDING_MANAGER", (
        f"resubmit of the revised draft should re-enter PENDING_MANAGER, got {resubmitted['status']}"
    )


# ─── Booking requires an approved trip ────────────────
def test_booking_on_pending_manager_trip_rejected(api):
    """PRD §3.3: "The trip must be in `APPROVED` or `BOOKED` — a booking attempted against
    a trip that has not cleared approval is refused with `ERR_APPROVAL_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_trip_approved
    """
    set_clock(CLOCK_DEFAULT)
    ctx = _pending_manager_trip()
    trav, ven = ctx["traveler"], make_vendor()
    v = trip_version(ctx["trip"]["id"], trav["id"])
    res = api.create_booking(
        create_booking_payload(ctx["trip"]["id"], ven["id"], v, segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=250000),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_APPROVAL_REQUIRED)


def test_booking_on_draft_trip_rejected(api):
    """PRD §3.3: "a booking attempted against a trip that has not cleared approval is
    refused with `ERR_APPROVAL_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_trip_approved
    """
    set_clock(CLOCK_DEFAULT)
    policy = make_policy()
    trav = make_traveler(policy["id"])
    ven = make_vendor()
    trip = make_trip(trav["id"], market_estimate_cents=50000)  # left in DRAFT
    v = trip_version(trip["id"], trav["id"])
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], v, segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=250000),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_APPROVAL_REQUIRED)


# ─── Submit requires an active traveler ───────────────
def test_suspended_traveler_cannot_submit_trip(api):
    """PRD §3.2: "The owning traveler must be `ACTIVE` at submit time; a submit by a
    suspended traveler is refused with `ERR_TRAVELER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_traveler_active
    """
    policy = make_policy()
    trav = make_traveler(policy["id"])
    validate_success(api.suspend_traveler(trav["id"], MGR))
    trip = make_trip(trav["id"], market_estimate_cents=50000)
    res = api.submit_trip_request(trip["id"], make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_TRAVELER_SUSPENDED)


def test_reactivated_traveler_can_submit_trip(api):
    """PRD §3.1: "A suspended traveler may later be reactivated, moving `status` back to
    `ACTIVE` with no further cascade."
    PRD §3.2: "When the level is `NONE`, submission moves the trip straight to `APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/submit_requires_traveler_active
    """
    policy = make_policy()
    trav = make_traveler(policy["id"])
    validate_success(api.suspend_traveler(trav["id"], MGR))
    trip = make_trip(trav["id"], market_estimate_cents=50000)
    validate_success(api.reactivate_traveler(trav["id"], MGR))
    submitted = submit_trip(trip["id"], trav["id"])
    assert submitted["status"] == "APPROVED", (
        f"an active traveler's NONE-level submit should reach APPROVED, got {submitted['status']}"
    )


# ─── Corner: initial state, invalid reactivation ──────
def test_new_trip_request_is_draft_with_zero_actual_cost(api):
    """PRD §3.2: "At creation the trip's `estimated_cost_cents` and `actual_cost_cents`
    are not yet meaningful (the latter defaults to 0), its `approval_level_required`
    defaults to `NONE`, and its `status` is `DRAFT`."

    Design: Corner/state_machines/trip_request_initial_state_is_draft
    """
    policy = make_policy()
    trav = make_traveler(policy["id"])
    trip = make_trip(trav["id"], market_estimate_cents=50000)
    assert trip["status"] == "DRAFT", f"new trip should be DRAFT, got {trip['status']}"
    assert trip["actual_cost_cents"] == 0, f"new trip actual_cost should be 0, got {trip['actual_cost_cents']}"


def test_reactivate_active_traveler_rejected(api):
    """PRD §3.1: "A suspended traveler may later be reactivated, moving `status` back to
    `ACTIVE`."
    PRD §2.7: "the target resource being in a state that permits the requested transition
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/reactivate_active_traveler_returns_invalid_state
    """
    policy = make_policy()
    trav = make_traveler(policy["id"])  # freshly ACTIVE
    res = api.reactivate_traveler(trav["id"], MGR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── Corner: self-approval and executive rank ─────────
def test_self_approval_rejected_when_state_precondition_met(api):
    """PRD §3.2: "an approver whose `X-User-ID` equals the trip's `traveler_id` is refused
    with `ERR_SELF_APPROVAL` on both approval and rejection, regardless of any other
    consideration."

    Design: Corner/validations/self_approval_isolated_returns_self_approval
    """
    policy = make_policy()
    trav = make_traveler(policy["id"], grade="MANAGER")
    trip = make_trip(trav["id"], market_estimate_cents=200000)
    trip = submit_trip(trip["id"], trav["id"])
    assert trip["status"] == "PENDING_MANAGER"
    res = api.approve_trip_request(trip["id"], make_approver_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_SELF_APPROVAL)


def test_manager_cannot_clear_executive_step(api):
    """PRD §3.2: "Clearing that `PENDING_EXEC` step demands an approver of `EXECUTIVE`
    grade specifically; an approver of insufficient rank is refused with
    `ERR_APPROVAL_RANK_TOO_LOW`."

    Design: Corner/validations/exec_step_manager_rank_too_low
    """
    policy = make_policy()
    trav = make_traveler(policy["id"])
    appr = make_traveler(policy["id"], grade="MANAGER")
    ven = make_vendor()
    make_rate(ven["id"], negotiated_fare_cents=600000, market_fare_cents=700000)
    trip = make_trip(trav["id"], market_estimate_cents=420000)
    trip = submit_trip(trip["id"], trav["id"])
    trip = approve_trip(trip["id"], appr["id"])  # PENDING_MANAGER -> PENDING_EXEC
    assert trip["status"] == "PENDING_EXEC", f"expected PENDING_EXEC, got {trip['status']}"
    res = api.approve_trip_request(trip["id"], make_approver_headers(appr["id"]))
    validate_error(res, ApiErrorId.ERR_APPROVAL_RANK_TOO_LOW)
