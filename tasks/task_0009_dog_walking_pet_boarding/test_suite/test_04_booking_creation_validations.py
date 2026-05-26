"""Booking-creation validation tests: priority pairs, calendar overlap rules
(sitter half-open + 30-min buffer vs pet closed inclusive no buffer),
Pet/Owner referential consistency, wallet sufficiency, Meet & Greet
prerequisite cross-entity dependency, claim-creation booking-status guard,
key-handoff uniqueness, and approved-amount bounds.

Covers queue A: priority_pair_validation_conflict, resource_temporal_overlap,
cross_entity_state_dependency. Covers queue B: validations / errors corner
instances pet_owner_mismatch_at_booking, error_wallet_insufficient_triggerable,
gps_not_in_progress_rejected, error_key_handoff_duplicate,
error_invalid_approved_amount_triggerable.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    create_owner_payload,
    create_sitter_payload,
    create_pet_payload,
    create_booking_payload,
    create_meet_and_greet_payload,
    create_key_handoff_payload,
    create_gps_track_payload,
    create_background_check_payload,
    TEST_USERS,
    make_owner_headers,
    make_sitter_headers,
    register_owner,
    register_sitter,
    create_pending_bg_check,
    clear_bg_check,
    setup_owner_sitter_pet,
    setup_approved_meet_and_greet,
    setup_confirmed_booking,
    setup_in_progress_booking,
    setup_under_review_claim,
    pin_clock,
    create_pet,
    setup_cleared_sitter,
)


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CLAIMS_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


# ---- Queue A: priority_pair_validation_conflict ------------------------------

def test_fk_not_found_wins_over_sitter_not_cleared_on_meet_and_greet_create(api):
    """PRD §2.8: "When more than one validation rule could fire for a
    single request, the server evaluates them in a fixed priority order
    so that error responses are deterministic."
    PRD §2.8: "(4) request-body foreign-key existence (`ERR_FK_NOT_FOUND`),
    (5) state-machine precondition (`ERR_INVALID_STATE`), (6) optimistic-concurrency
    token (`ERR_STALE_VERSION`), (7) sitter background-check clearance
    (`ERR_SITTER_NOT_CLEARED`)"
    PRD §2.8: "The first rule to fire is the one whose `error_id` is
    returned; lower-priority rules do not run."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_pair_meet_and_greet_create
    """
    owner = register_owner()
    pet = create_pet(owner["id"])
    pin_clock("2026-06-08T08:00:00Z")
    # sitter_id refers to non-existent sitter (FK fail at priority 4)
    # AND the sitter would not be CLEARED (priority 7).
    # FK_NOT_FOUND must win.
    payload = create_meet_and_greet_payload(
        owner["id"], "00000000-0000-0000-0000-000000000000", pet["id"],
        "2026-06-08T09:00:00Z",
    )
    res = api.create_meet_and_greet(payload, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_meet_and_greet_create_with_pet_fk_missing_also_fails_with_fk_not_found(api):
    """PRD §2.7: "Foreign keys passed in a `POST` request body — `owner_id`,
    `sitter_id`, `pet_id`, `booking_id` — are validated against their
    parent tables; a non-existent reference is rejected with
    `ERR_FK_NOT_FOUND` (HTTP 404)."
    PRD §2.8: "The first rule to fire is the one whose `error_id` is
    returned; lower-priority rules do not run."

    A second instance of the (existence) vs (business_safety) ordering: a
    pet_id pointing to a non-existent Pet on /meet-and-greets, with a
    sitter that lacks a CLEARED background check, must still surface
    ERR_FK_NOT_FOUND.

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_pair_meet_and_greet_create
    """
    owner = register_owner()
    # Create a Sitter without clearing BG — would trigger ERR_SITTER_NOT_CLEARED
    # if we got that far. But pet_id is bogus, so FK error must fire first.
    sitter = register_sitter()  # APPLIED, no BG
    pin_clock("2026-06-08T08:00:00Z")
    payload = create_meet_and_greet_payload(
        owner["id"], sitter["id"], "00000000-0000-0000-0000-000000000000",
        "2026-06-08T09:00:00Z",
    )
    res = api.create_meet_and_greet(payload, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_meet_and_greet_required_wins_over_wallet_insufficient_on_booking_create(api):
    """PRD §2.8: "(8) Meet & Greet completion + sitter availability
    (`ERR_MEET_AND_GREET_REQUIRED`), (9) pet-owner referential consistency
    (`ERR_PET_OWNER_MISMATCH`), (10) sitter calendar overlap
    (`ERR_SITTER_TIME_CONFLICT`), (11) pet calendar overlap
    (`ERR_PET_TIME_CONFLICT`), (12) primary emergency contact uniqueness
    (`ERR_PRIMARY_CONTACT_EXISTS`), (13) per-sitter background-check
    uniqueness (`ERR_BG_CHECK_EXISTS`), (14) per-booking key-handoff
    uniqueness (`ERR_KEY_HANDOFF_EXISTS`), (15) wallet credit sufficiency
    (`ERR_WALLET_INSUFFICIENT`), (16) insurance approved-amount bounds
    (`ERR_INVALID_APPROVED_AMOUNT`), (17) GPS-track booking-status guard
    (`ERR_GPS_BOOKING_NOT_IN_PROGRESS`), (18) request-body shape
    (`ERR_INVALID_REQUEST`)"
    PRD §2.8: "The first rule to fire is the one whose `error_id` is
    returned; lower-priority rules do not run."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair_booking_create
    """
    owner = register_owner()
    sitter = setup_cleared_sitter()
    pet = create_pet(owner["id"])
    pin_clock("2026-06-08T08:00:00Z")
    # No MeetAndGreet has ever been approved for (owner, sitter, pet).
    # Also wallet_credit_applied_cents=99999 vastly exceeds Owner.wallet=0.
    payload = create_booking_payload(
        owner["id"], sitter["id"], pet["id"],
        "2026-06-08T09:00:00Z", "2026-06-08T10:00:00Z",
        service_type="WALK_60MIN",
        wallet_credit_applied_cents=99999,
    )
    res = api.create_booking(payload, make_owner_headers(owner["id"]))
    # PRD priority: 8 (MEET_AND_GREET_REQUIRED) wins over 15 (WALLET_INSUFFICIENT).
    validate_error(res, "ERR_MEET_AND_GREET_REQUIRED")


def test_meet_and_greet_required_wins_over_wallet_insufficient_at_smaller_amount(api):
    """PRD §2.8: "(8) Meet & Greet completion + sitter availability
    (`ERR_MEET_AND_GREET_REQUIRED`), (9) pet-owner referential consistency
    (`ERR_PET_OWNER_MISMATCH`), (10) sitter calendar overlap
    (`ERR_SITTER_TIME_CONFLICT`), (11) pet calendar overlap
    (`ERR_PET_TIME_CONFLICT`), (12) primary emergency contact uniqueness
    (`ERR_PRIMARY_CONTACT_EXISTS`), (13) per-sitter background-check
    uniqueness (`ERR_BG_CHECK_EXISTS`), (14) per-booking key-handoff
    uniqueness (`ERR_KEY_HANDOFF_EXISTS`), (15) wallet credit sufficiency
    (`ERR_WALLET_INSUFFICIENT`)"
    PRD §2.8: "The first rule to fire is the one whose `error_id` is
    returned; lower-priority rules do not run."

    A second exercise of the (business_safety) vs (business_fiscal)
    priority pair with a different fiscal violation: even a small
    wallet_credit_applied_cents (1 cent) over the Owner's zero balance
    is a fiscal violation, but the missing MG (business_safety) still
    wins. Demonstrates that priority is independent of the magnitude
    of the lower-priority violation.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_pair_booking_create
    """
    owner = register_owner()
    sitter = setup_cleared_sitter()
    pet = create_pet(owner["id"])
    pin_clock("2026-06-08T08:00:00Z")
    # No MeetAndGreet for (owner, sitter, pet). wallet_credit_applied_cents=1
    # against Owner.wallet_credit_cents=0 would alone trigger
    # ERR_WALLET_INSUFFICIENT (priority 15). Priority 8 must still win.
    payload = create_booking_payload(
        owner["id"], sitter["id"], pet["id"],
        "2026-06-08T09:00:00Z", "2026-06-08T10:00:00Z",
        service_type="WALK_60MIN",
        wallet_credit_applied_cents=1,
    )
    res = api.create_booking(payload, make_owner_headers(owner["id"]))
    validate_error(res, "ERR_MEET_AND_GREET_REQUIRED")


# ---- Queue A: resource_temporal_overlap --------------------------------------

def test_sitter_calendar_half_open_buffer_blocks_back_to_back_booking(api):
    """PRD §3.4: "The sitter calendar check rejects with
    `ERR_SITTER_TIME_CONFLICT` when any existing booking for the same
    sitter that is not in `COMPLETED`, `CANCELLED`, `REJECTED`, or
    `EMERGENCY_TERMINATED` has a half-open interval running from its
    `start_at` through its `end_at` plus 30 minutes of trailing travel
    buffer that overlaps the proposed half-open interval from `start_at`
    to `end_at`."

    Design: Difficulty/resource_temporal_overlap/sitter_calendar_half_open_with_thirty_minute_buffer
    """
    # Owner + two pets + one Sitter.
    owner = register_owner()
    sitter = setup_cleared_sitter()
    pet_a = create_pet(owner["id"], name="PetA", weight_kg=10)
    pet_b = create_pet(owner["id"], name="PetB", weight_kg=12)
    pin_clock("2026-06-13T08:00:00Z")
    # Approve MGs for both pets with the same sitter.
    for pet_id in (pet_a["id"], pet_b["id"]):
        mg = validate_success(api.create_meet_and_greet(
            create_meet_and_greet_payload(owner["id"], sitter["id"], pet_id,
                                           "2026-06-13T07:30:00Z"),
            make_owner_headers(owner["id"]),
        ), 201)
        validate_success(api.approve_meet_and_greet(mg["id"], make_owner_headers(owner["id"])), 200)
    # First booking on pet_a: 09:00–10:00.
    booking_a = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet_a["id"],
                                "2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.confirm_booking(booking_a["id"], make_sitter_headers(sitter["id"])), 200)
    # Second booking on pet_b starting exactly at the prior end_at = 10:00.
    # Sitter calendar adds a 30-min buffer to the prior end, so the prior
    # window covers [09:00, 10:30) — overlap with [10:00, 11:00).
    res = api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet_b["id"],
                                "2026-06-13T10:00:00Z", "2026-06-13T11:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_SITTER_TIME_CONFLICT")


def test_sitter_calendar_after_buffer_window_does_not_conflict(api):
    """PRD §3.4: "The sitter calendar check rejects with
    `ERR_SITTER_TIME_CONFLICT` when any existing booking for the same
    sitter that is not in `COMPLETED`, `CANCELLED`, `REJECTED`, or
    `EMERGENCY_TERMINATED` has a half-open interval running from its
    `start_at` through its `end_at` plus 30 minutes of trailing travel
    buffer that overlaps the proposed half-open interval from `start_at`
    to `end_at`."

    The complement of the buffer rule: a proposed booking starting strictly
    AFTER end_at + 30 minutes is outside the buffer and must NOT conflict.

    Design: Difficulty/resource_temporal_overlap/sitter_calendar_half_open_with_thirty_minute_buffer
    """
    owner = register_owner()
    sitter = setup_cleared_sitter()
    pet_a = create_pet(owner["id"], name="PetA", weight_kg=10)
    pet_b = create_pet(owner["id"], name="PetB", weight_kg=12)
    pin_clock("2026-06-13T08:00:00Z")
    for pet_id in (pet_a["id"], pet_b["id"]):
        mg = validate_success(api.create_meet_and_greet(
            create_meet_and_greet_payload(owner["id"], sitter["id"], pet_id,
                                           "2026-06-13T07:30:00Z"),
            make_owner_headers(owner["id"]),
        ), 201)
        validate_success(api.approve_meet_and_greet(mg["id"], make_owner_headers(owner["id"])), 200)
    booking_a = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet_a["id"],
                                "2026-06-13T09:00:00Z", "2026-06-13T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.confirm_booking(booking_a["id"], make_sitter_headers(sitter["id"])), 200)
    # Proposed second booking starts at 10:30 (== end + buffer). Buffer
    # is on the trailing edge using half-open semantics: [09:00, 10:30)
    # vs proposed [10:30, 11:30) — no overlap.
    res = api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet_b["id"],
                                "2026-06-13T10:30:00Z", "2026-06-13T11:30:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    )
    booking_b = validate_success(res, expected_status=201)
    assert booking_b["status"] == "REQUESTED"


def test_pet_calendar_closed_inclusive_blocks_endpoint_overlap(api):
    """PRD §3.4: "The pet calendar check rejects with `ERR_PET_TIME_CONFLICT`
    when any existing booking for the same pet that is not in those four
    terminal states has a closed interval from its `start_at` to its
    `end_at` that inclusively intersects the proposed closed
    `[start_at, end_at]` — the pet must be in at most one active booking
    at any instant, with no buffer."

    Design: Difficulty/resource_temporal_overlap/pet_calendar_closed_inclusive_no_buffer
    """
    owner = register_owner()
    sitter_a = setup_cleared_sitter()
    sitter_b = setup_cleared_sitter()
    pet = create_pet(owner["id"], name="Pip", weight_kg=8)
    pin_clock("2026-06-14T08:00:00Z")
    for sitter_id in (sitter_a["id"], sitter_b["id"]):
        mg = validate_success(api.create_meet_and_greet(
            create_meet_and_greet_payload(owner["id"], sitter_id, pet["id"],
                                           "2026-06-14T07:30:00Z"),
            make_owner_headers(owner["id"]),
        ), 201)
        validate_success(api.approve_meet_and_greet(mg["id"], make_owner_headers(owner["id"])), 200)
    booking_a = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter_a["id"], pet["id"],
                                "2026-06-14T09:00:00Z", "2026-06-14T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.confirm_booking(booking_a["id"], make_sitter_headers(sitter_a["id"])), 200)
    # Second booking on the same pet covering [10:00, 11:00] — shares the
    # endpoint 10:00 with the prior closed window [09:00, 10:00].
    res = api.create_booking(
        create_booking_payload(owner["id"], sitter_b["id"], pet["id"],
                                "2026-06-14T10:00:00Z", "2026-06-14T11:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_PET_TIME_CONFLICT")


def test_pet_calendar_no_buffer_allows_strictly_disjoint_intervals(api):
    """PRD §3.4: "The pet calendar check rejects with `ERR_PET_TIME_CONFLICT`
    when any existing booking for the same pet that is not in those four
    terminal states has a closed interval from its `start_at` to its
    `end_at` that inclusively intersects the proposed closed
    `[start_at, end_at]` — the pet must be in at most one active booking
    at any instant, with no buffer."

    Complement: bookings that do not inclusively intersect — for example a
    second booking starting one minute AFTER the prior end_at — must NOT
    conflict (the pet rule has no buffer).

    Design: Difficulty/resource_temporal_overlap/pet_calendar_closed_inclusive_no_buffer
    """
    owner = register_owner()
    sitter_a = setup_cleared_sitter()
    sitter_b = setup_cleared_sitter()
    pet = create_pet(owner["id"], name="Pip", weight_kg=8)
    pin_clock("2026-06-14T08:00:00Z")
    for sitter_id in (sitter_a["id"], sitter_b["id"]):
        mg = validate_success(api.create_meet_and_greet(
            create_meet_and_greet_payload(owner["id"], sitter_id, pet["id"],
                                           "2026-06-14T07:30:00Z"),
            make_owner_headers(owner["id"]),
        ), 201)
        validate_success(api.approve_meet_and_greet(mg["id"], make_owner_headers(owner["id"])), 200)
    booking_a = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter_a["id"], pet["id"],
                                "2026-06-14T09:00:00Z", "2026-06-14T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    ), 201)
    validate_success(api.confirm_booking(booking_a["id"], make_sitter_headers(sitter_a["id"])), 200)
    # Strictly-after window: [10:00:01, 11:00:00] — no inclusive overlap.
    res = api.create_booking(
        create_booking_payload(owner["id"], sitter_b["id"], pet["id"],
                                "2026-06-14T10:00:01Z", "2026-06-14T11:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    )
    booking_b = validate_success(res, expected_status=201)
    assert booking_b["status"] == "REQUESTED"


# ---- Queue A: cross_entity_state_dependency ---------------------------------

def test_booking_create_without_approved_meet_and_greet_rejected(api):
    """PRD §3.4: "Creation rejection precedence: if the Meet & Greet
    prerequisite is unmet or the sitter is not `ACTIVE`, the response
    is `ERR_MEET_AND_GREET_REQUIRED`; if the supplied `pet_id`'s owner
    does not match the supplied `owner_id`, the response is
    `ERR_PET_OWNER_MISMATCH` — an owner cannot book another owner's pet."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_meet_and_greet_completed_approved
    """
    owner = register_owner()
    sitter = setup_cleared_sitter()
    pet = create_pet(owner["id"])
    pin_clock("2026-06-11T08:00:00Z")
    # Create a Meet & Greet but DO NOT approve it — remains in SCHEDULED.
    mg = validate_success(api.create_meet_and_greet(
        create_meet_and_greet_payload(owner["id"], sitter["id"], pet["id"],
                                       "2026-06-11T07:30:00Z"),
        make_owner_headers(owner["id"]),
    ), 201)
    assert mg["status"] == "SCHEDULED"
    res = api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_MEET_AND_GREET_REQUIRED")


def test_booking_create_succeeds_once_meet_and_greet_approved(api):
    """PRD §3.4: "Creation rejection precedence: if the Meet & Greet
    prerequisite is unmet or the sitter is not `ACTIVE`, the response
    is `ERR_MEET_AND_GREET_REQUIRED`; if the supplied `pet_id`'s owner
    does not match the supplied `owner_id`, the response is
    `ERR_PET_OWNER_MISMATCH` — an owner cannot book another owner's pet."

    The complement of the rejection rule: once the prerequisite MG is
    APPROVED for the (owner, sitter, pet) tuple, booking creation must
    succeed. This is the positive half of the same cross-entity
    dependency between Booking and MeetAndGreet.

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_meet_and_greet_completed_approved
    """
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-11T08:00:00Z", mg_scheduled_at="2026-06-11T07:30:00Z",
    )
    assert mg["status"] == "COMPLETED_APPROVED"
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-11T09:00:00Z", "2026-06-11T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert booking["status"] == "REQUESTED"


def test_insurance_claim_create_on_requested_booking_rejected(api):
    """PRD §3.8: "The targeted booking's `status` must be `IN_PROGRESS`,
    `COMPLETED`, or `EMERGENCY_TERMINATED` — claims filed against bookings
    in any other status are rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/insurance_claim_create_requires_booking_in_progress_or_terminal_state
    """
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-06-12T08:00:00Z", mg_scheduled_at="2026-06-12T07:30:00Z",
    )
    # Create REQUESTED Booking (do NOT confirm/start).
    booking = validate_success(api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-06-12T09:00:00Z", "2026-06-12T10:00:00Z",
                                service_type="WALK_60MIN"),
        make_owner_headers(owner["id"]),
    ), 201)
    assert booking["status"] == "REQUESTED"
    res = api.create_insurance_claim(
        {"booking_id": booking["id"], "claim_amount_cents": 5000},
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_insurance_claim_create_on_in_progress_booking_succeeds(api):
    """PRD §3.8: "The targeted booking's `status` must be `IN_PROGRESS`,
    `COMPLETED`, or `EMERGENCY_TERMINATED` — claims filed against bookings
    in any other status are rejected with `ERR_INVALID_STATE`."

    Complement: a Booking in IN_PROGRESS satisfies the cross-entity
    state precondition, so claim creation must succeed.

    Design: Difficulty/cross_entity_state_dependency/insurance_claim_create_requires_booking_in_progress_or_terminal_state
    """
    owner, sitter, pet, mg, booking, kh = setup_in_progress_booking(
        clock_iso="2026-06-12T08:00:00Z",
        mg_scheduled_at="2026-06-12T07:30:00Z",
        booking_start_at="2026-06-12T09:00:00Z",
        booking_end_at="2026-06-12T10:00:00Z",
    )
    assert booking["status"] == "IN_PROGRESS"
    claim = validate_success(api.create_insurance_claim(
        {"booking_id": booking["id"], "claim_amount_cents": 5000},
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    assert claim["status"] == "SUBMITTED"


# ---- Queue B: corner validations / errors ------------------------------------

def test_pet_owner_mismatch_at_booking_create(api):
    """PRD §3.4: "if the supplied `pet_id`'s owner does not match the
    supplied `owner_id`, the response is `ERR_PET_OWNER_MISMATCH` — an
    owner cannot book another owner's pet."

    Design: Corner/validations/pet_owner_mismatch_at_booking
    """
    owner_a = register_owner()
    owner_b = register_owner()
    sitter = setup_cleared_sitter()
    pet_a = create_pet(owner_a["id"], name="PetA", weight_kg=10)
    pin_clock("2026-06-28T08:00:00Z")
    # Owner B approves an MG with sitter using owner_a's pet.
    mg = validate_success(api.create_meet_and_greet(
        create_meet_and_greet_payload(owner_b["id"], sitter["id"], pet_a["id"],
                                       "2026-06-28T07:30:00Z"),
        make_owner_headers(owner_b["id"]),
    ), 201)
    validate_success(api.approve_meet_and_greet(mg["id"], make_owner_headers(owner_b["id"])), 200)
    # Owner B attempts booking on Owner A's pet — pet_owner_mismatch.
    res = api.create_booking(
        create_booking_payload(owner_b["id"], sitter["id"], pet_a["id"],
                                "2026-06-28T09:00:00Z", "2026-06-28T09:30:00Z",
                                service_type="WALK_30MIN"),
        make_owner_headers(owner_b["id"]),
    )
    validate_error(res, "ERR_PET_OWNER_MISMATCH")


def test_wallet_insufficient_on_booking_create(api):
    """PRD §3.4: "The wallet credit guard, `ERR_WALLET_INSUFFICIENT`,
    fires when the supplied `wallet_credit_applied_cents` exceeds either
    the owner's current `wallet_credit_cents` (cannot apply more credit
    than the balance) or the just-computed `booking_quote_cents` (cannot
    apply more credit than the quote itself)."

    Design: Corner/errors/error_wallet_insufficient_triggerable
    """
    owner, sitter, pet, mg = setup_approved_meet_and_greet(
        clock_iso="2026-07-01T08:00:00Z", mg_scheduled_at="2026-07-01T07:30:00Z",
    )
    # Owner.wallet_credit_cents == 0 by default. Apply 500 cents of credit.
    res = api.create_booking(
        create_booking_payload(owner["id"], sitter["id"], pet["id"],
                                "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z",
                                service_type="WALK_30MIN",
                                wallet_credit_applied_cents=500),
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_WALLET_INSUFFICIENT")


def test_gps_on_confirmed_booking_rejected(api):
    """PRD §3.5: "A GPS write is rejected with
    `ERR_GPS_BOOKING_NOT_IN_PROGRESS` (HTTP 409) when the named booking's
    `status` is anything other than `IN_PROGRESS`."

    Design: Corner/validations/gps_not_in_progress_rejected
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-06-29T08:00:00Z",
        mg_scheduled_at="2026-06-29T07:30:00Z",
        booking_start_at="2026-06-29T09:00:00Z",
        booking_end_at="2026-06-29T10:00:00Z",
    )
    # Booking is CONFIRMED, never started. GPS write must be rejected.
    res = api.create_gps_track(
        create_gps_track_payload(booking["id"], "2026-06-29T08:30:00Z",
                                  latitude=40.0, longitude=-74.0),
        make_sitter_headers(sitter["id"]),
    )
    validate_error(res, "ERR_GPS_BOOKING_NOT_IN_PROGRESS")


def test_key_handoff_duplicate_rejected(api):
    """PRD §3.5: "A second handoff create for the same booking is rejected
    with `ERR_KEY_HANDOFF_EXISTS`."

    Design: Corner/errors/error_key_handoff_duplicate
    """
    owner, sitter, pet, mg, booking = setup_confirmed_booking(
        clock_iso="2026-07-03T08:00:00Z",
        mg_scheduled_at="2026-07-03T07:30:00Z",
        booking_start_at="2026-07-03T09:00:00Z",
        booking_end_at="2026-07-03T10:00:00Z",
    )
    # First handoff succeeds.
    validate_success(api.create_key_handoff(
        create_key_handoff_payload(booking["id"], method="LOCKBOX", lockbox_code="1111"),
        make_owner_headers(owner["id"]),
    ), expected_status=201)
    # Second handoff for the same booking — must be rejected.
    res = api.create_key_handoff(
        create_key_handoff_payload(booking["id"], method="IN_PERSON"),
        make_owner_headers(owner["id"]),
    )
    validate_error(res, "ERR_KEY_HANDOFF_EXISTS")


def test_approved_amount_above_claim_amount_rejected(api):
    """PRD §3.8: "Approval advances `UNDER_REVIEW → APPROVED`, requires
    the request body to carry `approved_amount_cents` strictly greater
    than zero and at most the claim's `claim_amount_cents` (otherwise
    `ERR_INVALID_APPROVED_AMOUNT`), records `approved_amount_cents` on
    the row, optionally records `adjuster_notes`, and computes the
    final variant of `claim_payout` into `final_payout_cents`."

    Design: Corner/errors/error_invalid_approved_amount_triggerable
    """
    owner, sitter, pet, mg, booking, kh, claim = setup_under_review_claim(
        claim_amount_cents=10000,
        completed_kwargs={"owner_rating": 4,
                          "clock_iso": "2026-07-02T08:00:00Z",
                          "mg_scheduled_at": "2026-07-02T07:30:00Z",
                          "booking_start_at": "2026-07-02T09:00:00Z",
                          "booking_end_at": "2026-07-02T10:00:00Z"},
    )
    # Try to approve at 15000 cents > claim_amount_cents 10000.
    res = api.approve_insurance_claim(
        claim["id"], {"approved_amount_cents": 15000}, CLAIMS_ADJUSTER
    )
    validate_error(res, "ERR_INVALID_APPROVED_AMOUNT")
