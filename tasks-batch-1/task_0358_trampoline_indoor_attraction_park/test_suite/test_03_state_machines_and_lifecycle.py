"""State machines and lifecycle: JumpPass parallel payment/admission axes, the
cyclic membership renewal loop, initial states, invalid transitions, idempotency,
no-show sweep, party booking fork (clean vs deposit-forfeit cancel), and confirm.

Translates difficulty queue non_linear_state_machine and corner state_machines /
endpoints.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park_with_clock, set_clock, create_slot, get_slot, get_slot_version,
    create_adult, sign_waiver,
    create_member, create_membership, create_member_with_membership,
    create_reservation_pass, create_jump_pass,
    setup_party_prereqs, create_party_booking, hold_party_deposit,
    create_add_on_payload,
    make_member_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─────────────────────────────────────────────────────────────────────
# non_linear_state_machine / jump_pass_parallel_payment_and_admission_axes  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_pay_advances_payment_axis_leaving_admission_reserved(api):
    """PRD §3.5: "A pass tracks two *independent* status axes that advance on their own
    triggers."
    PRD §3.6: "Collecting payment advances the payment axis from `UNPAID` to `PAID`."

    After /pay on a RESERVED pass, payment_status == PAID while admission_status stays
    RESERVED — a combined state unreachable on a linear machine.

    Design: Difficulty/non_linear_state_machine/jump_pass_parallel_payment_and_admission_axes
    """
    park = create_park_with_clock("2026-06-20T09:55:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Adult J")
    sign_waiver(participant["id"], participant["id"], signature_text="Adult J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    paid = validate_success(api.pay_jump_pass(pas["id"], FD), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["admission_status"] == "RESERVED"


def test_admission_axis_advances_independently_after_pay(api):
    """PRD §3.6: "Admitting a reservation advances the admission axis from `RESERVED` to
    `CHECKED_IN` ... It requires four things, evaluated as a unit: the pass's `channel`
    is `RESERVATION`; a valid waiver covers the participant ...; the pass is already
    `PAID`; and the park's current clock falls within the check-in window."

    After pay (payment PAID, admission RESERVED), a check-in moves admission to
    CHECKED_IN while payment stays PAID — the two axes evolve on separate triggers.

    Design: Difficulty/non_linear_state_machine/jump_pass_parallel_payment_and_admission_axes
    """
    park = create_park_with_clock("2026-06-20T09:55:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Adult J")
    sign_waiver(participant["id"], participant["id"], signature_text="Adult J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    validate_success(api.pay_jump_pass(pas["id"], FD), 200)
    checked = validate_success(api.check_in_jump_pass(pas["id"], FD), 200)
    assert checked["admission_status"] == "CHECKED_IN"
    assert checked["payment_status"] == "PAID"


# ─────────────────────────────────────────────────────────────────────
# non_linear_state_machine / membership_cyclic_active_pastdue_active_loop  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_membership_failed_renewal_goes_past_due_freezes_inclusion(api):
    """PRD §3.7: "A failed renewal from `ACTIVE` moves the membership to `PAST_DUE` and
    freezes inclusion by setting `included_visits_remaining` to 0."

    SILVER membership, clock advanced past one cycle; renew FAILED -> status PAST_DUE,
    included_visits_remaining 0.

    Design: Difficulty/non_linear_state_machine/membership_cyclic_active_pastdue_active_loop
    """
    park = create_park_with_clock("2026-06-01T00:00:00Z")
    member = create_member(park["id"], email="cyc@x.com", full_name="Cyc M")
    membership = create_membership(member["id"], tier="SILVER", cycle_anchor_at="2026-06-01T00:00:00Z")
    mh = make_member_headers(member["id"])
    set_clock("2026-07-05T00:00:00Z")
    past_due = validate_success(api.renew_membership(membership["id"], {"outcome": "FAILED"}, mh), 200)
    assert past_due["status"] == "PAST_DUE"
    assert past_due["included_visits_remaining"] == 0


def test_membership_cure_back_to_active_resets_inclusion(api):
    """PRD §3.7: "A `PAST_DUE` membership is **cured** by a successful renewal, which
    advances `current_cycle_index` by 1, sets the status back to `ACTIVE`, and resets
    `included_visits_remaining` to the tier allotment."

    From PAST_DUE, a SUCCEEDED renewal cures back to ACTIVE and resets SILVER inclusion
    to 4 — a back-edge to a prior state on the same entity.

    Design: Difficulty/non_linear_state_machine/membership_cyclic_active_pastdue_active_loop
    """
    park = create_park_with_clock("2026-06-01T00:00:00Z")
    member = create_member(park["id"], email="cyc2@x.com", full_name="Cyc M")
    membership = create_membership(member["id"], tier="SILVER", cycle_anchor_at="2026-06-01T00:00:00Z")
    mh = make_member_headers(member["id"])
    set_clock("2026-07-05T00:00:00Z")
    validate_success(api.renew_membership(membership["id"], {"outcome": "FAILED"}, mh), 200)
    cured = validate_success(api.renew_membership(membership["id"], {"outcome": "SUCCEEDED"}, mh), 200)
    assert cured["status"] == "ACTIVE"
    assert cured["included_visits_remaining"] == 4


# ─────────────────────────────────────────────────────────────────────
# Corner state_machines — initial states, invalid transitions, idempotency
# ─────────────────────────────────────────────────────────────────────
def test_pass_starts_in_reserved_initial_state(api):
    """PRD §3.5: "A reservation pass is born `RESERVED`" and "every pass starts
    `UNPAID`."

    A new RESERVATION pass has admission_status RESERVED and payment_status UNPAID.

    Design: Corner/state_machines/pass_starts_in_reserved_initial_state
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Init J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    assert pas["admission_status"] == "RESERVED"
    assert pas["payment_status"] == "UNPAID"


def test_walkin_pass_starts_checked_in(api):
    """PRD §3.5: "a walk-in pass is born already `CHECKED_IN` (the guest is at the
    desk)."

    A new WALKIN pass has admission_status CHECKED_IN (skips RESERVED).

    Design: Corner/state_machines/walkin_pass_starts_checked_in
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Walk J")
    sign_waiver(participant["id"], participant["id"], signature_text="Walk J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    assert pas["admission_status"] == "CHECKED_IN"


def test_complete_pass_from_reserved_invalid_state(api):
    """PRD §3.6: "Marking a `CHECKED_IN` pass as `COMPLETED` is a `FrontDesk` action
    allowed only from `admission_status` `CHECKED_IN`."

    Completing a RESERVED (never checked-in) pass is not a legal transition ->
    ERR_INVALID_STATE (409).

    Design: Corner/state_machines/complete_pass_from_reserved_returns_invalid_state
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Inv J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    validate_error(api.complete_jump_pass(pas["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_twice_returns_already_paid(api):
    """PRD §3.6: "A second pay attempt on a pass that is already `PAID`, `REFUNDED`, or
    `PARTIALLY_REFUNDED` is rejected with `ERR_ALREADY_PAID`."

    Paying a pass that is already PAID -> ERR_ALREADY_PAID (409).

    Design: Corner/state_machines/pay_twice_returns_already_paid
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Pay J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    validate_success(api.pay_jump_pass(pas["id"], FD), 200)
    validate_error(api.pay_jump_pass(pas["id"], FD), ApiErrorId.ERR_ALREADY_PAID.value)


def test_incident_signed_off_is_terminal(api):
    """PRD §3.9: "**Signing off** a `REVIEWED` report moves it to the terminal
    `SIGNED_OFF`."
    PRD §3.9: "Any review, sign-off, or void requested from a state the path does not
    allow is rejected with `ERR_INVALID_STATE`."

    From SIGNED_OFF (terminal), a void is illegal -> ERR_INVALID_STATE (409).

    Design: Corner/state_machines/incident_signed_off_is_terminal
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Inc J")
    sign_waiver(participant["id"], participant["id"], signature_text="Inc J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    inc = validate_success(
        api.create_incident({"park_id": park["id"], "jump_pass_id": pas["id"],
                             "severity": "MINOR", "narrative": "bump"}, FD), 201)
    validate_success(api.review_incident(inc["id"], PM), 200)
    validate_success(api.sign_off_incident(inc["id"], PM), 200)
    validate_error(api.void_incident(inc["id"], PM), ApiErrorId.ERR_INVALID_STATE.value)


def test_no_show_sweep_releases_seats_after_slot_end(api):
    """PRD §3.2: "every pass still sitting in `RESERVED` (its holder never checked in) is
    moved to `NO_SHOW`, which releases that pass's seat and recomputes the slot's
    `status`."

    A still-RESERVED pass after slot end: sweep-no-shows -> admission NO_SHOW,
    seats_taken 1 -> 0.

    Design: Corner/state_machines/no_show_sweep_releases_seats_after_slot_end
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=5, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="NS J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    set_clock("2026-06-20T12:30:00Z")  # past ends_at
    validate_success(api.sweep_no_shows(slot["id"], PM), 200)
    swept = validate_success(api.get_jump_pass(pas["id"], FD), 200)
    assert swept["admission_status"] == "NO_SHOW"
    assert get_slot(slot["id"])["seats_taken"] == 0


# ─────────────────────────────────────────────────────────────────────
# Corner state_machines / endpoints — party booking fork
# ─────────────────────────────────────────────────────────────────────
def test_party_clean_cancel_before_deposit_keeps_seats_zero(api):
    """PRD §3.8: "A `PENDING` booking cancels cleanly: it goes to `CANCELLED` with no
    seats held, no deposit forfeited, and no change to the slot."

    Cancelling a PENDING booking sets booking_status CANCELLED and leaves slot
    seats_taken at 0.

    Design: Corner/state_machines/party_clean_cancel_before_deposit_keeps_seats_zero
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    cancelled = validate_success(api.cancel_party_booking(booking["id"], FD), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert get_slot(slot["id"])["seats_taken"] == 0


def test_party_deposit_held_cancel_forfeits_deposit(api):
    """PRD §3.8: "From `DEPOSIT_HELD`, cancelling goes to `CANCELLED`, releases the held
    guest seats ... and forfeits the deposit — `balance_paid_cents` stays at
    `deposit_cents` and nothing is refunded."

    A 6-guest no-member booking (total 19000, deposit round(19000*0.25)=4750) held then
    cancelled: booking_status CANCELLED, balance_paid_cents 4750, slot seats 0.

    Design: Corner/state_machines/party_deposit_held_cancel_forfeits_deposit
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    held = hold_party_deposit(booking["id"], slot["id"])
    assert held["deposit_cents"] == 4750
    cancelled = validate_success(api.cancel_party_booking(booking["id"], FD), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["balance_paid_cents"] == 4750
    assert get_slot(slot["id"])["seats_taken"] == 0


def test_confirm_collects_balance_to_total(api):
    """PRD §3.8: "From `DEPOSIT_HELD`, **confirming** the booking sets
    `balance_paid_cents` to the full `total_cents` and moves it to `CONFIRMED`."

    A deposit-held 6-guest no-member booking (total 19000): confirm sets
    balance_paid_cents == total_cents == 19000, booking_status CONFIRMED.

    Design: Corner/endpoints/confirm_collects_balance_computed_read
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    assert booking["total_cents"] == 19000
    hold_party_deposit(booking["id"], slot["id"])
    confirmed = validate_success(api.confirm_party_booking(booking["id"], FD), 200)
    assert confirmed["balance_paid_cents"] == 19000
    assert confirmed["booking_status"] == "CONFIRMED"
