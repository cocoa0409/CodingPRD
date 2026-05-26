"""State-machine tests: initial states, terminal-state lockdown, invalid
transitions, non-linear cycles on Sitter (ACTIVE↔SUSPENDED) and InsuranceClaim
(UNDER_REVIEW↔APPROVED), Meet & Greet branching, no-show 60-minute gate.

Covers queue A non_linear_state_machine instances and queue B
state_machines / endpoints corner instances.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_booking_payload,
    create_meet_and_greet_payload,
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    setup_owner_sitter_pet,
    setup_approved_meet_and_greet,
    setup_confirmed_booking,
    setup_under_review_claim,
    setup_approved_claim,
    setup_suspended_sitter_via_bg_flag,
    register_owner,
    register_sitter,
    create_pending_bg_check,
    clear_bg_check,
    flag_bg_check,
    pin_clock,
    create_pet,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---- Queue B: Booking initial state ------------------------------------------

def test_booking_initial_state_is_requested(api):
    """PRD §3.4: "On a successful create, the booking is persisted with
    `status` `REQUESTED`, `booking_quote_cents` set to the computed quote,
    `provisional_sitter_payout_cents` and `final_sitter_payout_cents`
    initialised to 0, `tip_cents` and `incident_deduction_cents`
    initialised to 0, `owner_rating` initialised to null, and
    `cancellation_reason` initialised to null."

    Design: Corner/state_machines/booking_initial_state_is_requested
    """
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-22T08:00:00Z", mg_scheduled_at="2026-06-22T07:30:00Z",
    )
    payload = create_booking_payload(
        owner["id"], sitter["id"], pet["id"],
        "2026-06-22T09:00:00Z", "2026-06-22T10:00:00Z",
        service_type="WALK_60MIN",
    )
    booking = validate_success(api.create_booking(payload, make_owner_headers(owner["id"])),
                                expected_status=201)
    assert booking["status"] == "REQUESTED"


# ---- Queue B: Terminal-state lockdown ----------------------------------------

def test_cancelled_booking_cannot_be_cancelled_again(api):
    """PRD §3.5: "Cancelling from the requested side (by the owner) follows
    the same compensation path: `cancellation_reason` is the supplied
    `reason`, the previously-applied wallet credit is restored, and
    `Owner.version` increments; this cancellation requires no version field
    because no cascade can have advanced the booking yet."
    PRD §2.8: validation priority 5: "(5) state-machine precondition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/booking_terminal_state_cannot_re_cancel
    """
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-22T08:00:00Z", mg_scheduled_at="2026-06-22T07:30:00Z",
    )
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-22T09:00:00Z", "2026-06-22T09:30:00Z",
                                service_type="WALK_30MIN"),
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.cancel_booking(booking["id"], {"reason": "first"},
                                          make_owner_headers(owner["id"])),
                       expected_status=200)
    # Second cancel attempt on a CANCELLED Booking — must be rejected.
    res = api.cancel_booking(booking["id"], {"reason": "second"}, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_complete_on_confirmed_booking_is_invalid(api):
    """PRD §3.5: "the same `ERR_SITTER_NOT_CLEARED` and
    `ERR_MEET_AND_GREET_REQUIRED` guards that protect Meet & Greet
    creation and Booking creation are re-checked at confirmation, and
    `ERR_INVALID_STATE` covers the start-time and source-state checks."

    The /complete endpoint requires Booking.status == IN_PROGRESS; per
    the PRD source-state-checks rule, calling /complete on a CONFIRMED
    booking surfaces ERR_INVALID_STATE.

    Design: Corner/state_machines/booking_invalid_transition_complete_from_confirmed
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking()
    # Try to complete a CONFIRMED (not IN_PROGRESS) booking.
    res = api.complete_booking(booking["id"], {}, make_sitter_headers(sitter["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_meet_and_greet_declined_cannot_be_approved_later(api):
    """PRD §3.3: "Any attempt to transition from a non-`SCHEDULED` source
    state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/meet_and_greet_branching_decline_terminal
    """
    owner, sitter, pet = setup_owner_sitter_pet(clock_iso="2026-06-23T08:00:00Z")
    mg = validate_success(api.create_meet_and_greet(
        create_meet_and_greet_payload(owner["id"], sitter["id"], pet["id"],
                                       "2026-06-23T07:30:00Z"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    # Decline first.
    validate_success(api.decline_meet_and_greet(mg["id"], make_owner_headers(owner["id"]),
                                                   payload={"notes": "not a fit"}),
                       expected_status=200)
    # Now try to approve — must be rejected.
    res = api.approve_meet_and_greet(mg["id"], make_owner_headers(owner["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_meet_and_greet_no_show_before_sixty_minutes_rejected(api):
    """PRD §3.3: "Only a `PlatformAdmin` may mark a no-show, transitioning
    `SCHEDULED → NO_SHOW`, and the operation is gated on the server clock
    being at least 60 minutes past the Meet & Greet's `scheduled_at`."

    Design: Corner/endpoints/action_endpoint_meet_and_greet_no_show_requires_60_min
    """
    owner, sitter, pet = setup_owner_sitter_pet(clock_iso="2026-06-30T08:00:00Z")
    mg = validate_success(api.create_meet_and_greet(
        create_meet_and_greet_payload(owner["id"], sitter["id"], pet["id"],
                                       "2026-06-30T09:00:00Z"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    # Advance the clock to T+30 minutes (< 60 min).
    pin_clock("2026-06-30T09:30:00Z")
    res = api.mark_no_show_meet_and_greet(mg["id"], PLATFORM_ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


# ---- Queue A: non_linear_state_machine — Sitter ACTIVE↔SUSPENDED cycle ------

def test_sitter_reinstate_after_bg_flag_clears_suspended_at(api):
    """PRD §3.2: "A `PlatformAdmin` may also reinstate a suspended sitter
    back to `ACTIVE`, which is the only cyclic edge in the sitter state
    machine: reinstating clears `Sitter.suspended_at` to null and bumps
    `Sitter.version`."

    Design: Difficulty/non_linear_state_machine/sitter_suspended_then_reinstated_cycle
    """
    sitter_suspended = setup_suspended_sitter_via_bg_flag()
    assert sitter_suspended["status"] == "SUSPENDED"
    assert sitter_suspended["suspended_at"] is not None
    # Reinstate via PlatformAdmin.
    reinstated = validate_success(
        api.reinstate_sitter(sitter_suspended["id"], PLATFORM_ADMIN),
        expected_status=200,
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspended_at"] is None


def test_sitter_reinstate_advances_version(api):
    """PRD §3.2: "A `PlatformAdmin` may also reinstate a suspended sitter
    back to `ACTIVE`, which is the only cyclic edge in the sitter state
    machine: reinstating clears `Sitter.suspended_at` to null and bumps
    `Sitter.version`."

    Design: Difficulty/non_linear_state_machine/sitter_suspended_then_reinstated_cycle
    """
    sitter_suspended = setup_suspended_sitter_via_bg_flag()
    v_before = sitter_suspended["version"]
    reinstated = validate_success(
        api.reinstate_sitter(sitter_suspended["id"], PLATFORM_ADMIN),
        expected_status=200,
    )
    # The transition itself bumps Sitter.version — strictly greater than
    # the pre-reinstate value.
    assert reinstated["version"] > v_before, (
        f"version must advance on reinstate: before={v_before}, after={reinstated['version']}"
    )
    assert reinstated["status"] == "ACTIVE"


# ---- Queue A: non_linear_state_machine — InsuranceClaim APPROVED↔UNDER_REVIEW

def test_insurance_claim_revert_clears_approved_amount_and_final_payout(api):
    """PRD §3.8: "Reverting an approved claim advances
    `APPROVED → UNDER_REVIEW`, clears `approved_amount_cents` back to null,
    and resets `final_payout_cents` to 0 — this is the cyclic edge on the
    insurance-claim state machine."

    Design: Difficulty/non_linear_state_machine/insurance_claim_approved_then_reverted_cycle
    """
    owner, sitter, pet, mg, booking, kh, claim = setup_approved_claim(
        claim_amount_cents=15000, approved_amount_cents=12000,
        completed_kwargs={"owner_rating": 4,
                          "clock_iso": "2026-06-05T08:00:00Z",
                          "mg_scheduled_at": "2026-06-05T07:30:00Z",
                          "booking_start_at": "2026-06-05T09:00:00Z",
                          "booking_end_at": "2026-06-05T10:00:00Z"},
    )
    assert claim["status"] == "APPROVED"
    reverted = validate_success(
        api.revert_insurance_claim(claim["id"], CLAIMS_ADJUSTER,
                                    payload={"adjuster_notes": "need more documentation"}),
        expected_status=200,
    )
    assert reverted["status"] == "UNDER_REVIEW"
    assert reverted["approved_amount_cents"] is None
    assert reverted["final_payout_cents"] == 0


def test_insurance_claim_revert_then_reapprove_completes_cycle(api):
    """PRD §3.8: "Reverting an approved claim advances
    `APPROVED → UNDER_REVIEW`, clears `approved_amount_cents` back to null,
    and resets `final_payout_cents` to 0 — this is the cyclic edge on the
    insurance-claim state machine."
    PRD §3.8: "Approval advances `UNDER_REVIEW → APPROVED`, requires the
    request body to carry `approved_amount_cents` strictly greater than
    zero and at most the claim's `claim_amount_cents` (otherwise
    `ERR_INVALID_APPROVED_AMOUNT`), records `approved_amount_cents` on
    the row, optionally records `adjuster_notes`, and computes the
    final variant of `claim_payout` into `final_payout_cents`."

    Design: Difficulty/non_linear_state_machine/insurance_claim_approved_then_reverted_cycle
    """
    owner, sitter, pet, mg, booking, kh, claim = setup_approved_claim(
        claim_amount_cents=15000, approved_amount_cents=12000,
        completed_kwargs={"owner_rating": 4,
                          "clock_iso": "2026-06-05T08:00:00Z",
                          "mg_scheduled_at": "2026-06-05T07:30:00Z",
                          "booking_start_at": "2026-06-05T09:00:00Z",
                          "booking_end_at": "2026-06-05T10:00:00Z"},
    )
    # First leg of the cycle: revert.
    reverted = validate_success(
        api.revert_insurance_claim(claim["id"], CLAIMS_ADJUSTER), expected_status=200
    )
    assert reverted["status"] == "UNDER_REVIEW"
    # Second leg: re-approve at a different amount — the claim re-enters
    # APPROVED (cyclic shape).
    reapproved = validate_success(
        api.approve_insurance_claim(claim["id"],
                                      {"approved_amount_cents": 8000,
                                       "adjuster_notes": "revised"},
                                      CLAIMS_ADJUSTER),
        expected_status=200,
    )
    assert reapproved["status"] == "APPROVED"
    assert reapproved["approved_amount_cents"] == 8000
