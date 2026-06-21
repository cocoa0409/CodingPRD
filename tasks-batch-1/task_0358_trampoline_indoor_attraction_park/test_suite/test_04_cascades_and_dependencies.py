"""Transitive cascades (paid-inclusion cancel depth-3, severe-incident slot-close
depth-2), cross-entity state dependencies (check-in depends on waiver; hold-deposit
depends on slot not closed), and compensating-action invariants (slot seats and
member included visits conserved on cancel).

Translates difficulty queue transitive_cascade, cross_entity_state_dependency, and
compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_park_with_clock, set_clock, create_slot, get_slot, get_slot_version,
    create_adult, sign_waiver,
    create_member, create_membership, create_member_with_membership,
    create_reservation_pass, create_jump_pass, create_paid_reservation_pass,
    setup_party_prereqs, create_party_booking, hold_party_deposit,
    file_incident,
    make_member_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─────────────────────────────────────────────────────────────────────
# transitive_cascade / cancel_paid_inclusion_pass_chain_depth3  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_cancel_paid_inclusion_pass_releases_seat_and_full_refund(api):
    """PRD §3.6: "Cancellation sets `admission_status` to `CANCELLED`, releases the seat
    (decrement `seats_taken`, recompute `status`) ... If the pass had been paid, the
    cancellation refund rule runs and writes the refund outcome onto the payment axis."
    PRD §3.6: "the refund equals everything actually paid (`amount_paid_cents`) and
    `payment_status` becomes `REFUNDED`."

    Capacity-1 GOLD inclusion pass paid (only socks 350 billed/paid); cancel >=120 min
    before start -> admission CANCELLED, slot back to OPEN/seats 0, refund 350.

    Design: Difficulty/transitive_cascade/cancel_paid_inclusion_pass_chain_depth3
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=1, base_price_cents=2000)
    member, _ = create_member_with_membership(park["id"], tier="GOLD", email="casc@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Casc J", member_id=member["id"], headers=mh)
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                  headers=mh, member_id=member["id"])
    validate_success(api.pay_jump_pass(pas["id"], mh), 200)  # inclusion path: paid 350
    assert get_slot(slot["id"])["status"] == "FULL"
    set_clock("2026-06-19T07:00:00Z")  # >= 120 min before slot start -> full refund
    cancelled = validate_success(api.cancel_jump_pass(pas["id"], mh), 200)
    assert cancelled["admission_status"] == "CANCELLED"
    assert cancelled["amount_refunded_cents"] == 350
    after = get_slot(slot["id"])
    assert after["seats_taken"] == 0
    assert after["status"] == "OPEN"


def test_cancel_paid_inclusion_pass_restores_inclusion(api):
    """PRD §3.6: "if the pass had consumed a membership inclusion, restores one
    `included_visits_remaining` to the membership."

    GOLD inclusion pass paid (8 -> 7 inclusion); cancelling that pass restores it back
    to 8 — the third cascade hop alongside the seat release.

    Design: Difficulty/transitive_cascade/cancel_paid_inclusion_pass_chain_depth3
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=1, base_price_cents=2000)
    member, membership = create_member_with_membership(park["id"], tier="GOLD", email="casc2@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Casc J", member_id=member["id"], headers=mh)
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                  headers=mh, member_id=member["id"])
    validate_success(api.pay_jump_pass(pas["id"], mh), 200)
    after_pay = validate_success(api.get_membership(membership["id"], mh), 200)
    assert after_pay["included_visits_remaining"] == 7
    set_clock("2026-06-19T07:00:00Z")
    validate_success(api.cancel_jump_pass(pas["id"], mh), 200)
    restored = validate_success(api.get_membership(membership["id"], mh), 200)
    assert restored["included_visits_remaining"] == 8


# ─────────────────────────────────────────────────────────────────────
# transitive_cascade / severe_incident_closes_slot_depth2  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_severe_incident_closes_slot_at_file_time(api):
    """PRD §3.9: "Filing a `SEVERE` incident force-closes the slot of the affected pass
    *at file time* (not at sign-off): the pass's `SessionSlot` is driven to `CLOSED` —
    `closed` becomes true and `status` becomes `CLOSED`".

    A WALKIN pass CHECKED_IN in an OPEN slot; filing a SEVERE incident -> incident FILED,
    the pass's slot closed=true and status CLOSED.

    Design: Difficulty/transitive_cascade/severe_incident_closes_slot_depth2
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Walk J")
    sign_waiver(participant["id"], participant["id"], signature_text="Walk J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    inc = validate_success(
        api.create_incident({"park_id": park["id"], "jump_pass_id": pas["id"],
                             "severity": "SEVERE", "narrative": "fall"}, FD), 201)
    assert inc["status"] == "FILED"
    after = get_slot(slot["id"])
    assert after["closed"] is True
    assert after["status"] == "CLOSED"


def test_minor_incident_does_not_close_slot(api):
    """PRD §3.9: "`MINOR` and `MODERATE` filings carry no such cascade."

    A WALKIN pass CHECKED_IN in an OPEN slot; filing a MINOR incident leaves the slot
    OPEN and not closed — the cascade fires only for SEVERE.

    Design: Difficulty/transitive_cascade/severe_incident_closes_slot_depth2
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Walk J")
    sign_waiver(participant["id"], participant["id"], signature_text="Walk J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    validate_success(
        api.create_incident({"park_id": park["id"], "jump_pass_id": pas["id"],
                             "severity": "MINOR", "narrative": "bump"}, FD), 201)
    after = get_slot(slot["id"])
    assert after["closed"] is False
    assert after["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / checkin_requires_signed_waiver_pass_depends_on_waiver (2)
# ─────────────────────────────────────────────────────────────────────
def test_checkin_without_waiver_rejected(api):
    """PRD §3.4: "When no such waiver exists at check-in time, admission is refused with
    `ERR_WAIVER_MISSING_OR_EXPIRED`. This safety gate is evaluated ahead of any
    temporal, capacity, or fiscal consideration."

    A paid reservation pass whose participant has NO waiver: check-in -> rejected
    ERR_WAIVER_MISSING_OR_EXPIRED (422).

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_signed_waiver_pass_depends_on_waiver
    """
    park = create_park_with_clock("2026-06-20T09:55:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="NoWaiver J")
    pas = create_paid_reservation_pass(slot, participant["id"])
    validate_error(api.check_in_jump_pass(pas["id"], FD),
                   ApiErrorId.ERR_WAIVER_MISSING_OR_EXPIRED.value)


def test_checkin_with_signed_waiver_succeeds(api):
    """PRD §3.6: "It requires four things, evaluated as a unit: the pass's `channel` is
    `RESERVATION`; a valid waiver covers the participant ...; the pass is already
    `PAID`; and the park's current clock falls within the check-in window."

    The same paid reservation pass, now WITH a SIGNED waiver and clock in-window:
    check-in succeeds and admission_status becomes CHECKED_IN.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_signed_waiver_pass_depends_on_waiver
    """
    park = create_park_with_clock("2026-06-20T09:55:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="HasWaiver J")
    sign_waiver(participant["id"], participant["id"], signature_text="HasWaiver J")
    pas = create_paid_reservation_pass(slot, participant["id"])
    checked = validate_success(api.check_in_jump_pass(pas["id"], FD), 200)
    assert checked["admission_status"] == "CHECKED_IN"


# ─────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / party_hold_deposit_depends_on_slot_not_closed  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_party_hold_deposit_on_closed_slot_rejected(api):
    """PRD §3.8: "It requires that the slot is not `CLOSED` and that the slot's
    `seats_taken` plus this booking's `guest_count` does not exceed the slot's
    `jump_capacity` (else `ERR_SLOT_CAPACITY_EXCEEDED`)".

    A pending booking on a slot the manager then CLOSES: hold-deposit is rejected
    ERR_SLOT_CAPACITY_EXCEEDED (409).

    Design: Difficulty/cross_entity_state_dependency/party_hold_deposit_depends_on_slot_not_closed
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    validate_success(api.close_slot(slot["id"], PM), 200)
    validate_error(
        api.hold_deposit(booking["id"],
                         {"expected_slot_version": get_slot_version(slot["id"])}, FD),
        ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)


def test_party_hold_deposit_on_open_slot_succeeds(api):
    """PRD §3.8: "On success the booking becomes `DEPOSIT_HELD`, the `deposit_cents` is
    computed and `balance_paid_cents` is set equal to it, the slot's `seats_taken` grows
    by `guest_count`".

    The same pending booking on an OPEN (non-closed) slot: hold-deposit succeeds and the
    booking reaches DEPOSIT_HELD, consuming the guest seats.

    Design: Difficulty/cross_entity_state_dependency/party_hold_deposit_depends_on_slot_not_closed
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 20, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=6)
    held = hold_party_deposit(booking["id"], slot["id"])
    assert held["booking_status"] == "DEPOSIT_HELD"
    assert get_slot(slot["id"])["seats_taken"] == 6


# ─────────────────────────────────────────────────────────────────────
# compensating_invariant / cancel_restores_slot_seat_conservation  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_create_then_cancel_restores_seats_to_zero(api):
    """PRD §3.6: "Cancellation sets `admission_status` to `CANCELLED`, releases the seat
    (decrement `seats_taken`, recompute `status`)".

    Empty capacity-1 slot: create a reservation pass (seats 1), then cancel it ->
    seats_taken back to 0, status OPEN (zero drift).

    Design: Difficulty/compensating_invariant/cancel_restores_slot_seat_conservation
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=1, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Comp J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    assert get_slot(slot["id"])["seats_taken"] == 1
    validate_success(api.cancel_jump_pass(pas["id"], FD), 200)
    after = get_slot(slot["id"])
    assert after["seats_taken"] == 0
    assert after["status"] == "OPEN"


def test_complete_pass_also_releases_seat(api):
    """PRD §3.6: "Completion releases the seat: the slot's `seats_taken` drops by 1 and
    the slot's `status` is recomputed (a `FULL` slot can fall back to `OPEN` if its
    occupancy drops below capacity)."

    Capacity-1 slot filled by a checked-in WALKIN pass (FULL): completing the pass
    releases the seat, returning seats_taken to 0 and status to OPEN.

    Design: Difficulty/compensating_invariant/cancel_restores_slot_seat_conservation
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=1, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="WalkComp J")
    sign_waiver(participant["id"], participant["id"], signature_text="WalkComp J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=1)
    assert get_slot(slot["id"])["status"] == "FULL"
    validate_success(api.complete_jump_pass(pas["id"], FD), 200)
    after = get_slot(slot["id"])
    assert after["seats_taken"] == 0
    assert after["status"] == "OPEN"


# ─────────────────────────────────────────────────────────────────────
# compensating_invariant / cancel_restores_member_included_visits_conservation  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_cancel_restores_member_included_visits(api):
    """PRD §3.6: "if the pass had consumed a membership inclusion, restores one
    `included_visits_remaining` to the membership."

    GOLD member (8 inclusions); paying an inclusion pass drops it to 7; cancelling that
    pass restores it to 8 — included-visits conserved with zero drift.

    Design: Difficulty/compensating_invariant/cancel_restores_member_included_visits_conservation
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    member, membership = create_member_with_membership(park["id"], tier="GOLD", email="inv@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Inv J", member_id=member["id"], headers=mh)
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                  headers=mh, member_id=member["id"])
    validate_success(api.pay_jump_pass(pas["id"], mh), 200)
    assert validate_success(api.get_membership(membership["id"], mh), 200)["included_visits_remaining"] == 7
    validate_success(api.cancel_jump_pass(pas["id"], mh), 200)
    restored = validate_success(api.get_membership(membership["id"], mh), 200)
    assert restored["included_visits_remaining"] == 8


def test_no_show_sweep_restores_member_included_visits(api):
    """PRD §3.2: "A swept pass forfeits its pass price — there is no refund — but if it
    had consumed a membership inclusion, that one included visit is restored to the
    member, exactly as a cancellation would restore it."

    GOLD member inclusion pass paid (8 -> 7); after slot end, sweep-no-shows on the
    still-RESERVED pass restores the inclusion to 8.

    Design: Difficulty/compensating_invariant/cancel_restores_member_included_visits_conservation
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    member, membership = create_member_with_membership(park["id"], tier="GOLD", email="ns@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="NS Inv J", member_id=member["id"], headers=mh)
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                  headers=mh, member_id=member["id"])
    validate_success(api.pay_jump_pass(pas["id"], mh), 200)
    assert validate_success(api.get_membership(membership["id"], mh), 200)["included_visits_remaining"] == 7
    set_clock("2026-06-20T12:30:00Z")  # past slot end
    validate_success(api.sweep_no_shows(slot["id"], PM), 200)
    restored = validate_success(api.get_membership(membership["id"], mh), 200)
    assert restored["included_visits_remaining"] == 8
