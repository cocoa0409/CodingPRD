"""Validation rules and the safety-before-fiscal priority principle on check-in:
guardian rule, signer rule, check-in window, unpaid-pass state, slot-window validity,
guest-count band, sock-count quantity, premature renewal, and the waiver-gate
precedence over later checks.

Translates difficulty queue priority_pair_validation_conflict (the check-in
safety-over-fiscal instance) and corner validations.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park_with_clock, set_clock, create_slot, get_slot_version,
    create_adult, create_guardian_and_minor, sign_waiver,
    create_member, create_membership,
    create_reservation_pass, create_paid_reservation_pass,
    setup_party_prereqs, create_party_booking,
    create_slot_payload, create_participant_payload, create_waiver_payload,
    create_party_booking_payload, create_jump_pass_payload, create_membership_payload,
    make_member_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─────────────────────────────────────────────────────────────────────
# priority_pair_validation_conflict / waiver_safety_beats_capacity_fiscal_on_checkin_vs_create (2)
#   (Only the check-in / waiver-first leg is PRD-uniquely-derivable. §3.4 + §2.7 pin
#    the waiver gate ahead of temporal and capacity/fiscal checks on check-in.)
# ─────────────────────────────────────────────────────────────────────
def test_checkin_no_waiver_in_full_slot_reports_waiver_error(api):
    """PRD §3.4: "When no such waiver exists at check-in time, admission is refused with
    `ERR_WAIVER_MISSING_OR_EXPIRED`. This safety gate is evaluated ahead of any
    temporal, capacity, or fiscal consideration."

    A paid reservation pass with NO waiver sits in a now-FULL capacity-2 slot; check-in
    surfaces the safety failure ERR_WAIVER_MISSING_OR_EXPIRED, not a capacity error.

    Design: Difficulty/priority_pair_validation_conflict/waiver_safety_beats_capacity_fiscal_on_checkin_vs_create
    """
    park = create_park_with_clock("2026-06-20T09:55:00Z")
    slot = create_slot(park["id"], jump_capacity=2, base_price_cents=2000)
    target = create_adult(park["id"], full_name="No Waiver J")
    target_pass = create_paid_reservation_pass(slot, target["id"])  # no waiver signed
    # Fill the slot with a second pass so seats_taken == capacity (FULL).
    filler = create_adult(park["id"], full_name="Filler J")
    create_reservation_pass(slot["id"], filler["id"], get_slot_version(slot["id"]))
    validate_error(api.check_in_jump_pass(target_pass["id"], FD),
                   ApiErrorId.ERR_WAIVER_MISSING_OR_EXPIRED.value)


def test_checkin_waiver_gate_precedes_temporal_window(api):
    """PRD §2.7: "on check-in the waiver gate fires first, then the temporal window".

    A paid reservation pass with NO waiver and the clock far before the window: the
    waiver gate fires first, so the error is ERR_WAIVER_MISSING_OR_EXPIRED rather than
    ERR_OUTSIDE_CHECKIN_WINDOW.

    Design: Difficulty/priority_pair_validation_conflict/waiver_safety_beats_capacity_fiscal_on_checkin_vs_create
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Early NoWaiver J")
    pas = create_paid_reservation_pass(slot, participant["id"])  # no waiver signed
    set_clock("2026-06-20T08:00:00Z")  # far before the check-in window
    validate_error(api.check_in_jump_pass(pas["id"], FD),
                   ApiErrorId.ERR_WAIVER_MISSING_OR_EXPIRED.value)


# ─────────────────────────────────────────────────────────────────────
# Corner validations
# ─────────────────────────────────────────────────────────────────────
def test_minor_without_guardian_rejected(api):
    """PRD §3.3: "Violating either side of this rule — a minor with no valid non-minor
    guardian in the same park, or an adult who supplied a guardian — is rejected with
    `ERR_GUARDIAN_REQUIRED`."

    A minor participant (birthdate 2016) created without guardian_participant_id ->
    ERR_GUARDIAN_REQUIRED (422).

    Design: Corner/validations/minor_without_guardian_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    validate_error(
        api.create_participant(
            create_participant_payload(park["id"], full_name="Lone Kid",
                                       birthdate="2016-01-01T00:00:00Z"), FD),
        ApiErrorId.ERR_GUARDIAN_REQUIRED.value)


def test_minor_waiver_signed_by_non_guardian_rejected(api):
    """PRD §3.4: "for a minor, the `signed_by_participant_id` must equal that
    participant's `guardian_participant_id`. A waiver whose signer violates this rule is
    rejected with `ERR_INVALID_SIGNER`."

    Signing a minor's waiver with signed_by == the minor (not the guardian) ->
    ERR_INVALID_SIGNER (422).

    Design: Corner/validations/minor_waiver_signed_by_non_guardian_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    guardian, minor = create_guardian_and_minor(park["id"])
    validate_error(
        api.create_waiver(
            create_waiver_payload(minor["id"], minor["id"], signature_text="Kid K"), FD),
        ApiErrorId.ERR_INVALID_SIGNER.value)


def test_checkin_too_early_outside_window_rejected(api):
    """PRD §3.6: "A check-in that is too early (before that lead-time boundary) or at/after
    the slot end is rejected with `ERR_OUTSIDE_CHECKIN_WINDOW`."

    A paid reservation pass WITH a signed waiver, clock 2 hours before slot start (more
    than the 30-min lead) -> ERR_OUTSIDE_CHECKIN_WINDOW (422).

    Design: Corner/validations/checkin_too_early_outside_window_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Early J")
    sign_waiver(participant["id"], participant["id"], signature_text="Early J")
    pas = create_paid_reservation_pass(slot, participant["id"])
    set_clock("2026-06-20T08:00:00Z")  # 2h before start, before the 30-min lead boundary
    validate_error(api.check_in_jump_pass(pas["id"], FD),
                   ApiErrorId.ERR_OUTSIDE_CHECKIN_WINDOW.value)


def test_checkin_unpaid_pass_invalid_state(api):
    """PRD §3.6: "It requires four things, evaluated as a unit: the pass's `channel` is
    `RESERVATION`; a valid waiver covers the participant ...; the pass is already
    `PAID`; and the park's current clock falls within the check-in window."
    PRD §2.7: "then state-machine legality for the requested transition
    (`ERR_INVALID_STATE`)."

    A RESERVED pass with a signed waiver and clock in-window but still UNPAID fails the
    PAID precondition -> ERR_INVALID_STATE (409).

    Design: Corner/validations/checkin_unpaid_pass_returns_invalid_state
    """
    park = create_park_with_clock("2026-06-20T09:55:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Unpaid J")
    sign_waiver(participant["id"], participant["id"], signature_text="Unpaid J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    validate_error(api.check_in_jump_pass(pas["id"], FD), ApiErrorId.ERR_INVALID_STATE.value)


def test_slot_window_ends_before_starts_rejected(api):
    """PRD §3.2: "The window must be valid: `ends_at` must fall strictly after
    `starts_at`, and a slot whose end is at or before its start is rejected with
    `ERR_INVALID_SLOT_WINDOW`."

    POST /park/slots with ends_at before starts_at -> ERR_INVALID_SLOT_WINDOW (422).

    Design: Corner/validations/slot_window_ends_before_starts_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    validate_error(
        api.create_slot(
            create_slot_payload(park["id"], starts_at="2026-06-20T12:00:00Z",
                                ends_at="2026-06-20T10:00:00Z"), PM),
        ApiErrorId.ERR_INVALID_SLOT_WINDOW.value)


def test_guest_count_below_min_guests_rejected(api):
    """PRD §3.8: "The `guest_count` must be at least the package's `min_guests` and at
    most the room's `room_capacity`; a count outside that band is rejected with
    `ERR_GUEST_COUNT_OUT_OF_RANGE`."

    A party booking with guest_count 2 below package.min_guests 4 ->
    ERR_GUEST_COUNT_OUT_OF_RANGE (422).

    Design: Corner/validations/guest_count_below_min_guests_rejected
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    validate_error(
        api.create_party_booking(
            create_party_booking_payload(package["id"], room["id"], slot["id"], guest_count=2),
            FD),
        ApiErrorId.ERR_GUEST_COUNT_OUT_OF_RANGE.value)


def test_zero_sock_count_rejected(api):
    """PRD §3.5: "The `sock_count` must be at least 1 — every jumper needs socks, so a
    `sock_count` of 0 or less is rejected with `ERR_INVALID_QUANTITY`".

    JumpPass create with sock_count 0 -> ERR_INVALID_QUANTITY (422).

    Design: Corner/validations/zero_sock_count_rejected
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Zero J")
    validate_error(
        api.create_jump_pass(
            create_jump_pass_payload(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                     sock_count=0), FD),
        ApiErrorId.ERR_INVALID_QUANTITY.value)


def test_premature_membership_renewal_rejected(api):
    """PRD §3.7: "A renewal from `ACTIVE` may only run once the park's current clock has
    reached the next cycle boundary ... a premature renewal from `ACTIVE` is rejected
    with `ERR_RENEWAL_NOT_DUE`."

    Renewing an ACTIVE membership while still inside cycle 0 (clock 2026-06-10, anchor
    2026-06-01) -> ERR_RENEWAL_NOT_DUE (409).

    Design: Corner/validations/premature_membership_renewal_rejected
    """
    park = create_park_with_clock("2026-06-10T00:00:00Z")
    member = create_member(park["id"], email="early@x.com", full_name="Early M")
    membership = create_membership(member["id"], tier="BRONZE", cycle_anchor_at="2026-06-01T00:00:00Z")
    mh = make_member_headers(member["id"])
    validate_error(api.renew_membership(membership["id"], {"outcome": "SUCCEEDED"}, mh),
                   ApiErrorId.ERR_RENEWAL_NOT_DUE.value)
