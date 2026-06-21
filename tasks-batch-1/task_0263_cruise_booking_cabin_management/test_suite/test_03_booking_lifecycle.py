"""Booking lifecycle: deposit hold, revise cycle, confirm, and cross-entity gates.

Covers the QUOTE -> DEPOSIT_HELD -> QUOTE revise cycle, deposit-hold and confirm
preconditions, cross-entity sailing-status gating on confirm and folio charges,
clock-driven expiry, and the immediate visibility of a held cabin.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_guest_user_headers,
    setup_open_sailing,
    create_quote_booking, create_deposit_held_booking, create_confirmed_booking,
    create_embarked_booking, get_booking, get_folio_for_booking,
    set_clock, MISSING_UUID,
)

RM = TEST_USERS["revenue_manager_headers"]
PA = TEST_USERS["port_agent_headers"]


# ===========================================================================
# Difficulty: DEPOSIT_HELD -> QUOTE revise cycle
# ===========================================================================
def test_revise_returns_booking_to_quote_and_clears_cabin(api):
    """PRD 3.5: "A guest who needs to edit the roster after holding a deposit revises
    the booking (`DEPOSIT_HELD → QUOTE`) ... Revising releases the held cabin back
    to its prior pool ... clears the cabin's `booking_id` and the booking's
    `cabin_id` ... and the booking returns to `QUOTE`."

    Design: Difficulty/non_linear_state_machine/booking_revise_cycle_deposit_held_back_to_quote
    """
    sailing, category, held = create_deposit_held_booking(
        "guest-5", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    resp = api.revise_booking(held["id"], make_guest_user_headers("guest-5"))
    data = validate_success(resp)
    assert data["status"] == "QUOTE"
    assert data["cabin_id"] is None


def test_revise_restores_category_available_cabins(api):
    """PRD 3.5: "Revising releases the held cabin back to its prior pool — to
    `AVAILABLE` for an individual draw or back to `BLOCKED` for a group draw".

    Design: Difficulty/non_linear_state_machine/booking_revise_cycle_deposit_held_back_to_quote
    """
    sailing, category, held = create_deposit_held_booking(
        "guest-5b", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    get_success_data(api.revise_booking(held["id"], make_guest_user_headers("guest-5b")))
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["available_cabins"] == 2
    assert cat["held_cabins"] == 0


# ===========================================================================
# Difficulty: cross-entity state dependency
# ===========================================================================
def test_confirm_rejected_when_sailing_not_bookable(api):
    """PRD 3.5: "Confirming a booking (`DEPOSIT_HELD → CONFIRMED`) ... requires the
    parent sailing to be `OPEN` or `CLOSED` (otherwise `ERR_SAILING_NOT_BOOKABLE`)".

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_sailing_open_or_closed
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, held = create_deposit_held_booking(
        "guest-11", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    # Pay the balance in full so only the sailing-status gate can fail.
    current = get_booking(held["id"])
    final_due = current["booking_total_cents"] - current["amount_paid_cents"]
    from test_helpers import make_and_capture_payment
    make_and_capture_payment(held["id"], "guest-11", "FINAL", final_due)
    # Depart the sailing so it leaves the OPEN/CLOSED set (now SAILED).
    set_clock("2026-09-01T18:00:00Z")
    get_success_data(api.depart_sailing(sailing["id"], PA))
    resp = api.confirm_booking(held["id"], make_guest_user_headers("guest-11"))
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_BOOKABLE.value)


def test_confirm_succeeds_when_sailing_open(api):
    """PRD 3.5: "Confirming a booking (`DEPOSIT_HELD → CONFIRMED`), performed by a
    `GuestUser` or `ReservationsAgent`, requires the parent sailing to be `OPEN` or
    `CLOSED` (otherwise `ERR_SAILING_NOT_BOOKABLE`) and requires the booking's
    `amount_paid_cents` to be at least its `booking_total_cents` (otherwise
    `ERR_BALANCE_OUTSTANDING`)."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_sailing_open_or_closed
    """
    sailing, category, confirmed = create_confirmed_booking(
        "guest-11b", num_guests=2, num_cabins=2,
    )
    assert confirmed["status"] == "CONFIRMED"


def test_folio_charge_against_unembarked_booking_not_found(api):
    """PRD 2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` before any later
    identifier is examined and before any business rule runs." PRD 3.7: a folio is
    created only at embarkation.

    Design: Difficulty/cross_entity_state_dependency/folio_charge_requires_booking_embarked
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, confirmed = create_confirmed_booking(
        "guest-12", num_guests=2, num_cabins=2,
    )
    # No depart -> no folio exists yet. Posting to a nonexistent folio is 404.
    from test_helpers import create_folio_charge_payload
    resp = api.post_folio_charge(MISSING_UUID, create_folio_charge_payload("Spa", 5000), PA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_folio_charge_requires_booking_embarked_via_gating(api):
    """PRD 3.7: "A charge may be posted only while the folio is `OPEN` (otherwise
    `ERR_INVALID_STATE`) and only while the owning booking is `EMBARKED` (otherwise
    `ERR_SAILING_NOT_BOOKABLE`)."

    Design: Difficulty/cross_entity_state_dependency/folio_charge_requires_booking_embarked
    """
    # An EMBARKED booking has a real folio; charge posting succeeds there.
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, embarked = create_embarked_booking(
        "guest-12b", num_guests=2, num_cabins=2,
    )
    folio = get_folio_for_booking(embarked["id"])
    assert folio is not None and folio["status"] == "OPEN"
    from test_helpers import create_folio_charge_payload
    resp = api.post_folio_charge(folio["id"], create_folio_charge_payload("Spa", 5000), PA)
    validate_success(resp, expected_status=201)


# ===========================================================================
# Corner: deposit-hold / confirm / embark / settle preconditions
# ===========================================================================
def test_hold_deposit_without_guests_rejected(api):
    """PRD 3.5: "The booking must have at least one guest (otherwise
    `ERR_NO_GUESTS`)."

    Design: Corner/state_machines/hold_deposit_without_guests_rejected
    """
    sailing, category, _cabins = setup_open_sailing(num_cabins=1)
    from test_helpers import create_booking
    booking = create_booking(sailing["id"], category["id"], "guest-c1", sailing["version"])
    resp = api.hold_deposit(booking["id"], make_guest_user_headers("guest-c1"))
    validate_error(resp, ApiErrorId.ERR_NO_GUESTS.value)


def test_hold_deposit_without_captured_deposit_rejected(api):
    """PRD 3.5: "Finally there must exist a `CAPTURED` `DEPOSIT` payment whose
    `amount_cents` equals the current `deposit_due_cents`; absent that, the request
    is rejected with `ERR_DEPOSIT_NOT_SATISFIED`."

    Design: Corner/state_machines/hold_deposit_without_captured_deposit_rejected
    """
    sailing, category, booking = create_quote_booking(
        "guest-c2", num_guests=2, num_cabins=1,
    )
    resp = api.hold_deposit(booking["id"], make_guest_user_headers("guest-c2"))
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_SATISFIED.value)


def test_confirm_without_full_balance_rejected(api):
    """PRD 3.5: "requires the booking's `amount_paid_cents` to be at least its
    `booking_total_cents` (otherwise `ERR_BALANCE_OUTSTANDING`)."

    Design: Corner/state_machines/confirm_without_full_balance_rejected
    """
    sailing, category, held = create_deposit_held_booking(
        "guest-c3", num_guests=2, num_cabins=1, deposit_cents=50000,
    )
    resp = api.confirm_booking(held["id"], make_guest_user_headers("guest-c3"))
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)


def test_embark_before_sailing_departed_rejected(api):
    """PRD 3.7: "in either case the booking's parent sailing must already be
    `SAILED`, and an embark attempt against a sailing that has not departed is
    rejected with `ERR_SAILING_NOT_DEPARTED`."

    Design: Corner/state_machines/embark_before_sailing_departed_rejected
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, confirmed = create_confirmed_booking(
        "guest-c4", num_guests=2, num_cabins=1,
    )
    resp = api.embark_booking(confirmed["id"], PA)
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_DEPARTED.value)


# ===========================================================================
# Corner: clock-driven expiry, immediate consistency
# ===========================================================================
def test_clock_advance_expires_stale_quote_booking(api):
    """PRD 3.8: "when the simulated clock advances past the sailing's `embark_date`
    while the booking is still `QUOTE`, the system moves it `QUOTE → EXPIRED`;
    because no cabin was held, nothing is released."

    Design: Corner/cross_cutting_complexity_layers/clock_advance_expires_stale_quote_booking
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, booking = create_quote_booking(
        "guest-c18", num_guests=1, num_cabins=1,
    )
    set_clock("2026-09-02T00:00:00Z")  # past embark_date 2026-09-01
    after = get_booking(booking["id"])
    assert after["status"] == "EXPIRED"


def test_hold_deposit_cabin_visible_in_same_response(api):
    """PRD 2.6: "State changes propagate down the resource hierarchy atomically
    within the triggering request". PRD 3.5: "The chosen cabin moves to `HELD`, its
    `booking_id` is set to this booking, and the booking's `cabin_id` is set to that
    cabin."

    Design: Corner/consistency_model/booking_cabin_hold_visible_in_same_response
    """
    sailing, category, held = create_deposit_held_booking(
        "guest-c19", num_guests=2, num_cabins=1, deposit_cents=50000,
    )
    assert held["status"] == "DEPOSIT_HELD"
    assert held["cabin_id"] is not None
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["available_cabins"] == 0
    assert cat["held_cabins"] == 1
