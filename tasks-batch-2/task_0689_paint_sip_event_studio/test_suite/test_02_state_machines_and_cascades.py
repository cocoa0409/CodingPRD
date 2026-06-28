"""Event/reservation state machines, multi-hop cancellation cascades,
cross-entity gates, and conservation invariants.

Difficulty queue (A): non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data, validate_error,
    make_customer_headers, TEST_USERS, ApiErrorId,
    create_studio, create_artist, create_customer, create_gift_card,
    setup_open_event_with_customer, book_reservation, pay_reservation,
    confirm_reservation, setup_confirmed_reservation, event_current_version,
    set_clock, assert_seat_ledger_consistent, assert_gift_card_value_conserved,
)

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


def _payment_rows(api, reservation_id):
    data, _meta = validate_paginated(
        api.list_payments(MANAGER, params={"reservation_id": reservation_id}))
    return data


# ─── non_linear_state_machine ───────────────────────────────────────────────

def test_event_open_full_open_cycle(api):
    """PRD §3.3: "whenever a seat-consuming mutation drives seats_available to
    exactly 0, the system transitions the event OPEN → FULL; whenever a
    seat-releasing mutation brings seats_available back above 0, the system
    transitions it FULL → OPEN."

    Design: Difficulty/non_linear_state_machine/nlsm_event_open_full_open_cycle
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=5, seats_capacity=5, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=5)

    full = get_success_data(api.get_event(event["id"], MANAGER))
    assert full["status"] == "FULL", f"5/5 seats -> FULL, got {full['status']}"
    assert full["seats_available"] == 0

    get_success_data(api.cancel_reservation(res["id"], make_customer_headers(customer["id"])))
    reopened = get_success_data(api.get_event(event["id"], MANAGER))
    assert reopened["status"] == "OPEN", f"freeing seats reverts FULL -> OPEN, got {reopened['status']}"
    assert reopened["seats_available"] == 5


def test_event_stays_open_until_last_seat_then_flips_full(api):
    """PRD §3.3: "whenever a seat-consuming mutation drives seats_available to
    exactly 0, the system transitions the event OPEN → FULL."

    Design: Difficulty/non_linear_state_machine/nlsm_event_open_full_open_cycle
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=5, seats_capacity=5, price_cents_per_seat=4500, clock=None)
    # Partial booking of 3/5 leaves seats_available > 0: still OPEN, not FULL.
    book_reservation(event["id"], customer["id"], seats=3)
    mid = get_success_data(api.get_event(event["id"], MANAGER))
    assert mid["status"] == "OPEN", f"3/5 seats keeps event OPEN, got {mid['status']}"
    assert mid["seats_available"] == 2

    # Topping up to exactly 0 flips OPEN -> FULL.
    book_reservation(event["id"], customer["id"], seats=2)
    full = get_success_data(api.get_event(event["id"], MANAGER))
    assert full["status"] == "FULL", f"last 2 seats -> FULL, got {full['status']}"
    assert full["seats_available"] == 0


def test_reservation_payment_and_booking_are_parallel_dimensions(api):
    """PRD §3.5: "The booking status and the payment status are two independent
    dimensions of the same reservation: payment does not by itself change the
    booking status, which remains HELD or CONFIRMED as it was."
    PRD §3.6: "Once a reservation's payment_status is PAID, a Customer or manager
    may confirm it, advancing the booking status HELD → CONFIRMED."

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_parallel_dimensions
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=20, seats_capacity=20, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=3)

    paid = pay_reservation(res["id"], customer["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["status"] == "HELD", (
        f"payment must not change booking status (still HELD), got {paid['status']}")

    confirmed = confirm_reservation(res["id"], customer["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "PAID", (
        f"confirm must not change payment dimension (still PAID), got {confirmed['payment_status']}")


def test_reservation_initial_dimensions_independent_at_create(api):
    """PRD §3.4: "A new reservation begins with booking status HELD and payment status
    UNPAID."
    PRD §3.5: "The booking status and the payment status are two independent
    dimensions of the same reservation."

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_parallel_dimensions
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=20, seats_capacity=20, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=3)
    # On create the two dimensions hold their independent initial values.
    assert res["status"] == "HELD"
    assert res["payment_status"] == "UNPAID"

    # Paying advances ONLY the payment dimension; booking stays HELD.
    paid = pay_reservation(res["id"], customer["id"])
    assert paid["status"] == "HELD", "booking dimension untouched by pay"
    assert paid["payment_status"] == "PAID", "payment dimension advanced by pay"


# ─── transitive_cascade ─────────────────────────────────────────────────────

def test_event_cancel_three_hop_cascade(api):
    """PRD §3.11: "In the first hop, each reservation in HELD, CONFIRMED, or
    CHECKED_IN is cancelled to CANCELLED with full credit ... In the second hop,
    each such reservation whose payment_status is PAID has its SETTLED CARD payments
    reversed to REVERSED and its payment_status set to REFUNDED. In the third hop,
    each affected customer's credit_balance_cents is increased by the cancelled
    reservation's total_cents."

    Design: Difficulty/transitive_cascade/tc_event_cancel_three_hop
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer, confirmed = setup_confirmed_reservation(
        seats=3, price_cents_per_seat=4500, room_capacity_seats=20, seats_capacity=20,
        clock=None)
    assert confirmed["total_cents"] == 13500

    get_success_data(api.cancel_event(event["id"], MANAGER))

    res_after = get_success_data(api.get_reservation(confirmed["id"], MANAGER))
    assert res_after["status"] == "CANCELLED", "hop1: reservation -> CANCELLED"
    assert res_after["payment_status"] == "REFUNDED", "hop2: payment_status -> REFUNDED"

    rows = _payment_rows(api, confirmed["id"])
    card_rows = [p for p in rows if p["method"] == "CARD"]
    assert card_rows and all(p["status"] == "REVERSED" for p in card_rows), (
        f"hop2: CARD payments must be REVERSED, got {card_rows}")

    cust_after = get_success_data(api.get_customer(customer["id"], MANAGER))
    assert cust_after["credit_balance_cents"] == 13500, (
        f"hop3: customer credited full total 13500, got {cust_after['credit_balance_cents']}")


def test_event_cancel_releases_assignments_and_walkins(api):
    """PRD §3.11: "In addition, each ArtistAssignment in ASSIGNED is released to
    RELEASED, and each WalkIn in REGISTERED or CHECKED_IN is cancelled to CANCELLED.
    The event's version is incremented by one as part of the cancellation."

    Design: Difficulty/transitive_cascade/tc_event_cancel_three_hop
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=20, name="CascB")
    artist = create_artist(full_name="Gi2")
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "CascB Class", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 20, "price_cents_per_seat": 4500}, MANAGER))
    assignment = get_success_data(api.create_assignment(
        {"event_id": event["id"], "artist_id": artist["id"]}, MANAGER))
    get_success_data(api.schedule_event(event["id"], MANAGER))
    get_success_data(api.open_event(event["id"], MANAGER))
    walk = get_success_data(api.create_walk_in(
        {"event_id": event["id"], "party_name": "Walkers", "party_size": 2}, FRONT_DESK))

    # Capture the event version immediately before the cancel. Registering a
    # walk-in recomputes the event's seat ledger (PRD §3.7), which per §2.11 is a
    # mutation that increments the event's version by one — so before_v must be
    # read *after* the walk-in to isolate the single bump the cancel contributes.
    before_v = event_current_version(event["id"])

    get_success_data(api.cancel_event(event["id"], MANAGER))

    ev_after = get_success_data(api.get_event(event["id"], MANAGER))
    assert ev_after["status"] == "CANCELLED"
    assert ev_after["version"] == before_v + 1, (
        f"event version bumps once on cancel, got {ev_after['version']} from {before_v}")
    asg_after = get_success_data(api.get_assignment(assignment["id"], MANAGER))
    assert asg_after["status"] == "RELEASED", "ASSIGNED assignment -> RELEASED"
    walk_after = get_success_data(api.get_walk_in(walk["id"], MANAGER))
    assert walk_after["status"] == "CANCELLED", "REGISTERED walk-in -> CANCELLED"


def test_event_close_noshow_sweep_releases_seats(api):
    """PRD §3.10: "Every reservation still in HELD or CONFIRMED is swept to NO_SHOW —
    its seats are released, no credit is granted, and it is excluded from the settled
    donation."

    Design: Difficulty/transitive_cascade/tc_event_close_noshow_seat_release
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=20, seats_capacity=20, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-02T10:00:00Z", end_utc="2026-04-02T12:00:00Z")
    res = book_reservation(event["id"], customer["id"], seats=4)

    set_clock("2026-04-02T11:00:00Z")
    closed = get_success_data(api.close_event(event["id"], MANAGER))
    assert closed["status"] == "CLOSED"
    assert closed["seats_reserved"] == 0, "hop2: NO_SHOW sweep releases the seats"
    assert closed["seats_available"] == 20

    res_after = get_success_data(api.get_reservation(res["id"], MANAGER))
    assert res_after["status"] == "NO_SHOW", "hop1: still-HELD reservation -> NO_SHOW"


def test_event_close_no_show_grants_no_credit_and_checks_in_walkins(api):
    """PRD §3.10: "Every reservation still in HELD or CONFIRMED is swept to NO_SHOW —
    its seats are released, no credit is granted, and it is excluded from the settled
    donation. Every walk-in still in REGISTERED is advanced to CHECKED_IN."

    Design: Difficulty/transitive_cascade/tc_event_close_noshow_seat_release
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=20, seats_capacity=20, price_cents_per_seat=4500,
        clock=None, start_utc="2026-04-02T10:00:00Z", end_utc="2026-04-02T12:00:00Z")
    res = book_reservation(event["id"], customer["id"], seats=2)
    walk = get_success_data(api.create_walk_in(
        {"event_id": event["id"], "party_name": "Walkers", "party_size": 3}, FRONT_DESK))

    set_clock("2026-04-02T11:00:00Z")
    get_success_data(api.close_event(event["id"], MANAGER))

    res_after = get_success_data(api.get_reservation(res["id"], MANAGER))
    assert res_after["status"] == "NO_SHOW"
    assert res_after["credit_granted_cents"] == 0, "NO_SHOW sweep grants no credit"
    walk_after = get_success_data(api.get_walk_in(walk["id"], MANAGER))
    assert walk_after["status"] == "CHECKED_IN", "REGISTERED walk-in -> CHECKED_IN at close"


# ─── cross_entity_state_dependency ──────────────────────────────────────────

def test_confirm_blocked_when_parent_event_cancelled(api):
    """PRD §3.6: "confirmation requires both that payment_status is PAID and that the
    parent event is in OPEN or FULL status, and an attempt that violates either is
    rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/cesd_confirm_requires_event_open
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=2)
    pay_reservation(res["id"], customer["id"])

    get_success_data(api.cancel_event(event["id"], MANAGER))

    resp = api.confirm_reservation(res["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_succeeds_while_parent_event_open(api):
    """PRD §3.6: "Once a reservation's payment_status is PAID, a Customer or manager
    may confirm it, advancing the booking status HELD → CONFIRMED; confirmation
    requires both that payment_status is PAID and that the parent event is in OPEN or
    FULL status."

    Design: Difficulty/cross_entity_state_dependency/cesd_confirm_requires_event_open
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=2)
    pay_reservation(res["id"], customer["id"])
    # Parent event is still OPEN, so the cross-entity gate is satisfied.
    confirmed = confirm_reservation(res["id"], customer["id"])
    assert confirmed["status"] == "CONFIRMED"


def test_assignment_blocked_for_inactive_artist(api):
    """PRD §3.2: "The artist must be ACTIVE; assigning an INACTIVE artist is rejected
    with ERR_ARTIST_INACTIVE (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/cesd_assignment_requires_active_artist
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=10, name="X2")
    artist = create_artist(full_name="Mo")
    get_success_data(api.deactivate_artist(artist["id"], MANAGER))
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "X2 Class", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))

    resp = api.create_assignment({"event_id": event["id"], "artist_id": artist["id"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_ARTIST_INACTIVE)


def test_assignment_succeeds_for_active_artist(api):
    """PRD §3.2: "A manager creates an assignment by supplying the event_id and the
    artist_id; the assignment begins ASSIGNED ... The artist must be ACTIVE; assigning
    an INACTIVE artist is rejected with ERR_ARTIST_INACTIVE (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/cesd_assignment_requires_active_artist
    """
    set_clock("2026-04-01T00:00:00Z")
    studio = create_studio(room_capacity_seats=10, name="X2b")
    artist = create_artist(full_name="Active Mo")  # left ACTIVE
    event = get_success_data(api.create_event({
        "studio_id": studio["id"], "title": "X2b Class", "event_type": "PUBLIC_CLASS",
        "start_utc": "2026-04-05T10:00:00Z", "end_utc": "2026-04-05T12:00:00Z",
        "seats_capacity": 10, "price_cents_per_seat": 4500}, MANAGER))
    resp = api.create_assignment({"event_id": event["id"], "artist_id": artist["id"]}, MANAGER)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ASSIGNED"


# ─── compensating_invariant ─────────────────────────────────────────────────

def test_seat_conservation_across_book_and_cancel(api):
    """PRD §2.8: "seats_available is the event's seats_capacity minus seats_reserved
    minus walk_in_seats, floored at zero so that it never reports a negative number."
    PRD §3.9: "The reservation's booking status moves to CANCELLED, its seats are
    released, the parent event's seat ledger is recomputed."

    Design: Difficulty/compensating_invariant/ci_seat_conservation_on_cancel
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    res = book_reservation(event["id"], customer["id"], seats=3)

    booked = get_success_data(api.get_event(event["id"], MANAGER))
    assert booked["seats_reserved"] == 3
    assert booked["seats_available"] == 7
    assert_seat_ledger_consistent(booked)

    get_success_data(api.cancel_reservation(res["id"], make_customer_headers(customer["id"])))
    after = get_success_data(api.get_event(event["id"], MANAGER))
    assert after["seats_reserved"] == 0, "seats released on cancel (no drift)"
    assert after["seats_available"] == 10
    assert_seat_ledger_consistent(after)


def test_seat_conservation_holds_with_reservation_and_walkin(api):
    """PRD §2.8: "seats_available is the event's seats_capacity minus seats_reserved
    minus walk_in_seats, floored at zero so that it never reports a negative number."
    PRD §3.7: "A walk-in may be cancelled, transitioning to CANCELLED, which releases
    its seats; the ledger is recomputed."

    Design: Difficulty/compensating_invariant/ci_seat_conservation_on_cancel
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    book_reservation(event["id"], customer["id"], seats=3)
    walk = get_success_data(api.create_walk_in(
        {"event_id": event["id"], "party_name": "Wk", "party_size": 2}, FRONT_DESK))

    mixed = get_success_data(api.get_event(event["id"], MANAGER))
    assert mixed["seats_reserved"] == 3 and mixed["walk_in_seats"] == 2
    assert mixed["seats_available"] == 5
    assert_seat_ledger_consistent(mixed)  # 10 == 5 + 3 + 2

    # Compensating cancel of the walk-in: the invariant must still hold, no drift.
    get_success_data(api.cancel_walk_in(walk["id"], FRONT_DESK))
    after = get_success_data(api.get_event(event["id"], MANAGER))
    assert after["walk_in_seats"] == 0 and after["seats_reserved"] == 3
    assert after["seats_available"] == 7
    assert_seat_ledger_consistent(after)  # 10 == 7 + 3 + 0


def test_gift_card_value_conserved_after_partial_redemption(api):
    """PRD §3.1: "As the card is drawn upon, balance_cents decreases and
    redeemed_cents increases, and the identity that balance_cents plus redeemed_cents
    equals issued_value_cents is always conserved."
    PRD §3.5: "for each card the amount drawn is the smaller of the card's
    balance_cents and the still-uncovered remainder."

    Design: Difficulty/compensating_invariant/ci_gift_card_value_conservation
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    gc = create_gift_card(code="GC-CONS", issued_value_cents=10000)
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["total_cents"] == 13500

    paid = pay_reservation(res["id"], customer["id"], gift_card_ids=[gc["id"]])
    assert paid["amount_paid_cents"] == 13500

    gc_after = get_success_data(api.get_gift_card(gc["id"], MANAGER))
    assert gc_after["balance_cents"] == 0, "card draws min(10000, 13500) == 10000"
    assert gc_after["redeemed_cents"] == 10000
    assert gc_after["status"] == "DEPLETED"
    assert_gift_card_value_conserved(gc_after)

    rows = _payment_rows(api, res["id"])
    card_rows = [p for p in rows if p["method"] == "CARD"]
    assert len(card_rows) == 1 and card_rows[0]["amount_cents"] == 3500, (
        f"CARD covers remaining 3500, got {card_rows}")


def test_gift_card_value_conserved_when_card_survives_active(api):
    """PRD §3.1: "As the card is drawn upon, balance_cents decreases and redeemed_cents
    increases, and the identity that balance_cents plus redeemed_cents equals
    issued_value_cents is always conserved."

    Design: Difficulty/compensating_invariant/ci_gift_card_value_conservation
    """
    set_clock("2026-04-01T00:00:00Z")
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=10, seats_capacity=10, price_cents_per_seat=4500, clock=None)
    # Card 20000 partially redeemed by a 13500 total — card stays ACTIVE with 6500 left.
    gc = create_gift_card(code="GC-SURV", issued_value_cents=20000)
    res = book_reservation(event["id"], customer["id"], seats=3)
    assert res["total_cents"] == 13500

    pay_reservation(res["id"], customer["id"], gift_card_ids=[gc["id"]])
    gc_after = get_success_data(api.get_gift_card(gc["id"], MANAGER))
    assert gc_after["balance_cents"] == 6500
    assert gc_after["redeemed_cents"] == 13500
    assert gc_after["status"] == "ACTIVE", "card with positive balance stays ACTIVE"
    assert_gift_card_value_conserved(gc_after)  # 6500 + 13500 == 20000
