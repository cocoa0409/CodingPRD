"""Trip / guest / claim state-machine transitions, branching, and cyclic review.

Difficulty rule non_linear_state_machine (branching from REQUESTED, cyclic
NEEDS_INFO loop) plus corner invalid/terminal transitions and immediate
read-after-write consistency.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_guest_headers, make_admin_headers,
    register_verified_guest,
    setup_requested_trip, setup_confirmed_trip, setup_completed_trip,
    setup_claim_under_review, get_booked_block,
)

ADMIN = make_admin_headers()


# ------------------------------------------------------- guest verification
def test_verify_already_verified_guest_rejected(api):
    """PRD §3.3: "The platform operator then either verifies the guest,
    advancing `PENDING_REVIEW → VERIFIED` ... `VERIFIED` is terminal."

    Design: Corner/state_machines/guest_double_verify_idempotency_rejected
    """
    guest = register_verified_guest(api, license_number="DL-24", name="Guest BD", email="gbd@x.com")
    resp = api.verify_guest(guest["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --------------------------------------------------- invalid trip transitions
def test_approve_already_confirmed_trip_rejected(api):
    """PRD §3.5: "A booking sits in `REQUESTED` until the owning host acts.
    Approving it advances `REQUESTED → CONFIRMED` and credits the host's
    `pending_balance_cents` by the trip's `estimated_host_earnings_cents`."

    Design: Corner/state_machines/approve_already_confirmed_trip_invalid
    """
    ctx = setup_confirmed_trip(api)
    resp = api.approve_trip(ctx["trip"]["id"], ctx["host_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_checkin_from_requested_trip_rejected(api):
    """PRD §3.6: "Once a trip is `CONFIRMED`, the guest who owns it takes
    possession by checking in, which advances `CONFIRMED → CHECKED_IN`."

    Design: Corner/state_machines/checkin_from_requested_invalid
    """
    ctx = setup_requested_trip(api)
    resp = api.checkin_trip(
        ctx["trip"]["id"],
        {"odometer_reading": 10000, "fuel_level_pct": 100, "photo_refs": ["in1"]},
        ctx["guest_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_completed_trip_rejected(api):
    """PRD §3.5: "Cancellation is available to either party — the guest who owns
    the trip or the host who owns its vehicle — while the trip is `REQUESTED` or
    `CONFIRMED`, advancing it to `CANCELLED`."

    Design: Corner/state_machines/cancel_completed_trip_terminal_locked
    """
    ctx = setup_completed_trip(api)
    resp = api.cancel_trip(ctx["trip"]["id"], ctx["host_headers"], {"reason": "too late"})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ------------------------------------------------- immediate consistency read
def test_booking_immediately_readable_with_estimate(api):
    """PRD §3.4: "At the moment of booking the system locks a full **estimated
    settlement** onto the trip" and "A new trip enters `REQUESTED`."

    Design: Corner/consistency_model/booking_immediately_readable
    """
    ctx = setup_requested_trip(api)
    resp = api.get_trip(ctx["trip"]["id"], ctx["guest_headers"])
    data = validate_success(resp)
    assert data["status"] == "REQUESTED"
    assert data["estimated_total_cents"] == 80500


# --------------------------------- Difficulty: branching from REQUESTED (decline)
def test_decline_branch_releases_block(api):
    """PRD §3.5: "Declining it advances `REQUESTED → DECLINED`, releases the
    linked `BOOKED` block to `RELEASED`, and reduces the vehicle's
    `booked_night_count` by the trip's `nights`; because a declined trip was
    never confirmed, there is no pending credit to reverse."

    Design: Difficulty/non_linear_state_machine/trip_branching_from_requested
    """
    ctx = setup_requested_trip(api)
    trip = get_success_data(api.decline_trip(ctx["trip"]["id"], ctx["host_headers"]))
    assert trip["status"] == "DECLINED"
    block = get_booked_block(api, ctx["trip"]["id"])
    assert block["status"] == "RELEASED"


def test_decline_branch_leaves_pending_and_nights_zero(api):
    """PRD §3.5: "Declining it advances `REQUESTED → DECLINED`, releases the
    linked `BOOKED` block to `RELEASED`, and reduces the vehicle's
    `booked_night_count` by the trip's `nights`; because a declined trip was
    never confirmed, there is no pending credit to reverse."

    Design: Difficulty/non_linear_state_machine/trip_branching_from_requested
    """
    ctx = setup_requested_trip(api)
    api.decline_trip(ctx["trip"]["id"], ctx["host_headers"])
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
    host = get_success_data(api.get_host(ctx["host"]["id"], ADMIN))
    assert vehicle["booked_night_count"] == 0
    assert host["pending_balance_cents"] == 0


# ------------------------------- Difficulty: cyclic NEEDS_INFO <-> UNDER_REVIEW
def test_claim_needs_info_cycle_traversed_twice_returns_under_review(api):
    """PRD §3.8: "the operator may request more information, advancing to
    `NEEDS_INFO`; a party to the trip (the claimant or the counterparty) then
    provides that information with an optional `note`, advancing
    `NEEDS_INFO → UNDER_REVIEW`, and this request/provide cycle may repeat."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_needs_info_loop
    """
    ctx = setup_claim_under_review(api)
    claim_id = ctx["claim"]["id"]
    api.request_info_claim(claim_id, ADMIN)
    api.provide_info_claim(claim_id, ctx["host_headers"], {"note": "photos"})
    api.request_info_claim(claim_id, ADMIN)
    final = get_success_data(api.provide_info_claim(claim_id, ctx["host_headers"], {"note": "more photos"}))
    assert final["status"] == "UNDER_REVIEW"


def test_claim_request_info_then_provide_info_returns_under_review(api):
    """PRD §3.8: "the operator may request more information, advancing to
    `NEEDS_INFO`; a party to the trip (the claimant or the counterparty) then
    provides that information with an optional `note`, advancing
    `NEEDS_INFO → UNDER_REVIEW`, and this request/provide cycle may repeat."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_needs_info_loop
    """
    ctx = setup_claim_under_review(api)
    claim_id = ctx["claim"]["id"]
    needs_info = get_success_data(api.request_info_claim(claim_id, ADMIN))
    assert needs_info["status"] == "NEEDS_INFO"
    back = get_success_data(api.provide_info_claim(claim_id, ctx["host_headers"], {"note": "info"}))
    assert back["status"] == "UNDER_REVIEW"
