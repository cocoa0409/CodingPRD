"""Reservation booking/settlement dimensions, refunds, exchange, no-show,
ticket voiding, GA capacity boundary, and conserved-quantity invariants.

Translates difficulty instances (parallel state, refund branch selection, GA
boundary, conservation) and the matching corner instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_ga_show_on_sale, setup_table_show_on_sale,
    create_ga_reservation, create_table_reservation, create_table_reservation_assigned,
    reservation_collected, set_clock,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty A — non_linear_state_machine / reservation_parallel_*_dims
# ---------------------------------------------------------------------------
def test_reservation_seated_can_stay_uncollected(api):
    """PRD §3.6: "Seating a party advances its `booking_status` from `BOOKED` to
    `SEATED`".
    PRD §3.6: "These two status dimensions are independent: a reservation may
    already be `TICKET_PAID` while still `BOOKED`, and a `CHECKED_IN` reservation
    may still owe its minimum."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_and_settlement_dims
    """
    sc = setup_table_show_on_sale(seats=4, price_cents=4500)
    res = create_table_reservation_assigned(sc, patron_id="patron-dd", party_size=2)
    seated = validate_success(api.seat_reservation(res["id"], FLOOR))
    assert seated["booking_status"] == "SEATED", \
        f"expected SEATED, got {seated['booking_status']}"
    assert seated["settlement_status"] == "UNCOLLECTED", \
        f"settlement dimension must stay UNCOLLECTED, got {seated['settlement_status']}"


def test_reservation_settlement_dim_advances_while_still_booked(api):
    """PRD §3.6: "A `BoxOffice` operator collects ticket payment, advancing
    `settlement_status` from `UNCOLLECTED` to `TICKET_PAID`; this requires the
    reservation's `booking_status` to be `BOOKED`, `SEATED`, or `CHECKED_IN`".
    PRD §3.6: "a reservation may already be `TICKET_PAID` while still `BOOKED`".

    Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_and_settlement_dims
    """
    sc = setup_ga_show_on_sale()
    res = create_ga_reservation(sc, patron_id="patron-dd2", party_size=2)
    collected = validate_success(api.collect_ticket(res["id"], BOX_OFFICE))
    assert collected["settlement_status"] == "TICKET_PAID", \
        f"expected TICKET_PAID, got {collected['settlement_status']}"
    assert collected["booking_status"] == "BOOKED", \
        f"booking dimension must stay BOOKED, got {collected['booking_status']}"


# ---------------------------------------------------------------------------
# Difficulty A — combinatorial_formula / refund_branch_selection_multi_input
# ---------------------------------------------------------------------------
def test_late_patron_cancel_retains_cancel_fee(api):
    """PRD §3.7: "A patron-initiated cancel keeps a cancellation fee unless it
    lands well before doors: if the logical clock is at or before `starts_at`
    minus 120 minutes, the full base is refunded; otherwise the refund is the base
    less a flat cancellation fee of 1500 cents, floored at zero."
    PRD §3.7: "the `ticket_charge_cents` counts toward the base whenever the
    reservation's `settlement_status` is `TICKET_PAID` or `MINIMUM_MET`".

    Design: Difficulty/combinatorial_formula/refund_branch_selection_multi_input
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "GA Night", "starts_at": "2026-04-03T03:00:00Z",
                        "ends_at": "2026-04-03T05:00:00Z"},
    )
    res = reservation_collected(sc, patron_id="patron-bb", party_size=3)
    assert res["ticket_charge_cents"] == 13500, "precondition: 4500*3 == 13500 collected"
    # Clock inside the 120-min late window (30 min before doors).
    set_clock("2026-04-03T02:30:00Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], BOX_OFFICE))
    # base 13500 - cancel fee 1500 == 12000.
    assert cancelled["refunded_cents"] == 12000, \
        f"late cancel refund expected 12000, got {cancelled['refunded_cents']}"
    assert cancelled["booking_status"] == "CANCELLED", \
        f"expected CANCELLED, got {cancelled['booking_status']}"
    assert cancelled["settlement_status"] == "REFUNDED", \
        f"expected REFUNDED, got {cancelled['settlement_status']}"


def test_early_patron_cancel_full_refund_no_fee(api):
    """PRD §3.7: "A patron-initiated cancel keeps a cancellation fee unless it
    lands well before doors: if the logical clock is at or before `starts_at`
    minus 120 minutes, the full base is refunded; otherwise the refund is the base
    less a flat cancellation fee of 1500 cents, floored at zero."

    Design: Difficulty/combinatorial_formula/refund_branch_selection_multi_input
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "GA Early Night", "starts_at": "2026-04-03T03:00:00Z",
                        "ends_at": "2026-04-03T05:00:00Z"},
    )
    res = reservation_collected(sc, patron_id="patron-bb2", party_size=3)
    assert res["ticket_charge_cents"] == 13500, "precondition: base 13500 collected"
    # Clock well outside the 120-min late window (more than 2h before doors).
    set_clock("2026-04-03T00:00:00Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], BOX_OFFICE))
    # Outside the late window -> full base refunded, no fee deducted.
    assert cancelled["refunded_cents"] == 13500, \
        f"early cancel must refund the full base 13500, got {cancelled['refunded_cents']}"
    assert cancelled["settlement_status"] == "REFUNDED", \
        f"expected REFUNDED, got {cancelled['settlement_status']}"


def test_exchange_downsell_credits_difference(api):
    """PRD §3.7: "On exchange the refund is a credit of the difference: the old
    base minus the ticket charge of the target tier (the target tier's
    `price_cents` times `party_size`), floored at zero so it is never negative."
    PRD §3.7: "The old row moves to `booking_status` `EXCHANGED` (terminal) and
    `settlement_status` `REFUNDED`".

    Design: Corner/calculations/exchange_downsell_credits_difference
    """
    # Build a show with two GA sections/tiers: VIP 9000 and GA 4500.
    sc = setup_ga_show_on_sale(
        ga_capacity=50, price_cents=9000,
        show_overrides={"title": "Exch Night", "starts_at": "2026-05-14T03:00:00Z",
                        "ends_at": "2026-05-14T05:00:00Z"},
        tier_overrides={"name": "VIP"},
    )
    venue_id, show_id = sc["venue"]["id"], sc["show"]["id"]
    ga_section = validate_success(
        api.create_section(venue_id, show_id, {"kind": "GA", "label": "Reg Standing", "ga_capacity": 50}, BOOKER),
        expected_status=201,
    )
    ga_tier = validate_success(
        api.create_tier(venue_id, show_id, {"section_id": ga_section["id"], "name": "GA", "price_cents": 4500}, BOOKER),
        expected_status=201,
    )
    res = reservation_collected(sc, patron_id="patron-ex", party_size=2)
    assert res["ticket_charge_cents"] == 18000, "precondition: VIP 9000*2 == 18000 collected"
    exchanged = validate_success(
        api.exchange_reservation(
            res["id"], {"target_section_id": ga_section["id"], "target_tier_id": ga_tier["id"]},
            BOX_OFFICE,
        )
    )
    assert exchanged["booking_status"] == "EXCHANGED", \
        f"expected EXCHANGED, got {exchanged['booking_status']}"
    # credit max(0, 18000 - 9000) == 9000.
    assert exchanged["refunded_cents"] == 9000, \
        f"exchange credit expected 9000, got {exchanged['refunded_cents']}"
    assert exchanged["settlement_status"] == "REFUNDED", \
        f"expected REFUNDED, got {exchanged['settlement_status']}"


# ---------------------------------------------------------------------------
# Difficulty A — boundary_precision_check / ga_capacity_exact_vs_over_by_one
# ---------------------------------------------------------------------------
def test_ga_reservation_exact_capacity_succeeds_and_sells_out(api):
    """PRD §3.5: "A reservation is admitted only when its `party_size` is less
    than or equal to the remaining capacity; a `party_size` strictly greater than
    the remaining capacity is rejected with `ERR_SECTION_SOLD_OUT`."
    PRD §3.5: "When a GA reservation brings the show's `ga_sold_count` up to a GA
    section's `ga_capacity` so that no GA section has remaining capacity, the show
    transitions from `ON_SALE` to `SOLD_OUT`".

    Design: Difficulty/boundary_precision_check/ga_capacity_exact_vs_over_by_one
    """
    sc = setup_ga_show_on_sale(ga_capacity=3)
    res = create_ga_reservation(sc, patron_id="patron-g1", party_size=3)
    assert res["booking_status"] == "BOOKED"
    show = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert show["status"] == "SOLD_OUT", \
        f"filling exact capacity must flip show to SOLD_OUT, got {show['status']}"


def test_ga_reservation_over_remaining_capacity_rejected(api):
    """PRD §3.5: "a `party_size` strictly greater than the remaining capacity is
    rejected with `ERR_SECTION_SOLD_OUT`."
    PRD §3.5: "after which further GA reservation creation is rejected with
    `ERR_SECTION_SOLD_OUT`."

    Design: Difficulty/boundary_precision_check/ga_capacity_exact_vs_over_by_one
    """
    sc = setup_ga_show_on_sale(ga_capacity=3)
    create_ga_reservation(sc, patron_id="patron-g1", party_size=3)  # fills to capacity
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-g2", "party_size": 1,
    }
    resp = api.create_reservation(payload, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_SECTION_SOLD_OUT)


# ---------------------------------------------------------------------------
# Difficulty A — compensating_invariant / ga_seat_count_conserved_on_cancel
# ---------------------------------------------------------------------------
def test_ga_sold_count_conserved_after_cancel(api):
    """PRD §3.7: "recomputes the show's `ga_sold_count`, which may auto-transition
    the show from `SOLD_OUT` back to `ON_SALE`."
    PRD §2.5: "A show's `ga_sold_count` is the running sum of `party_size` across
    that show's reservations whose section is a GA section and whose
    `booking_status` is `BOOKED`, `SEATED`, or `CHECKED_IN`; it is recomputed
    whenever a reservation is created, cancelled, exchanged, or otherwise leaves
    those states."

    Design: Difficulty/compensating_invariant/ga_seat_count_conserved_on_cancel
    """
    sc = setup_ga_show_on_sale(ga_capacity=10)
    res = create_ga_reservation(sc, patron_id="patron-jj", party_size=3)
    after_book = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert after_book["ga_sold_count"] == 3, \
        f"expected ga_sold_count 3 after booking, got {after_book['ga_sold_count']}"
    cancelled = validate_success(api.cancel_reservation(res["id"], BOX_OFFICE))
    assert cancelled["booking_status"] == "CANCELLED"
    after_cancel = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert after_cancel["ga_sold_count"] == 0, \
        f"ga_sold_count must return to 0 after cancel, got {after_cancel['ga_sold_count']}"


def test_ga_capacity_reopens_after_cancel_frees_seats(api):
    """PRD §3.5: "A reservation is admitted only when its `party_size` is less
    than or equal to the remaining capacity; a `party_size` strictly greater than
    the remaining capacity is rejected with `ERR_SECTION_SOLD_OUT`."
    PRD §3.7: "recomputes the show's `ga_sold_count`, which may auto-transition
    the show from `SOLD_OUT` back to `ON_SALE`."

    Design: Difficulty/compensating_invariant/ga_seat_count_conserved_on_cancel
    """
    # Capacity 3 filled exactly, then a cancel frees all 3 seats: a new party of 3
    # is admissible again, proving the headcount was conserved (returned to 0).
    sc = setup_ga_show_on_sale(ga_capacity=3)
    res = create_ga_reservation(sc, patron_id="patron-jj2", party_size=3)
    sold_out = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert sold_out["status"] == "SOLD_OUT", "precondition: exact-capacity sale sells out"
    validate_success(api.cancel_reservation(res["id"], BOX_OFFICE))
    reopened = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert reopened["ga_sold_count"] == 0, \
        f"ga_sold_count must be conserved to 0 after cancel, got {reopened['ga_sold_count']}"
    # A fresh party of 3 fits again (capacity fully restored).
    again = create_ga_reservation(sc, patron_id="patron-jj3", party_size=3)
    assert again["booking_status"] == "BOOKED", \
        "freed capacity must admit a new party of 3"


# ---------------------------------------------------------------------------
# Difficulty A — compensating_invariant / server_load_conserved_on_table_release
# ---------------------------------------------------------------------------
def test_no_show_frees_table_but_conserves_server_load(api):
    """PRD §3.7: "A no-show may be marked from `BOOKED`, `SEATED`, or
    `CHECKED_IN`, sets `booking_status` to `NO_SHOW`, retains the ticket charge
    with no refund so `refunded_cents` is zero, and releases any held table back
    to `AVAILABLE`."
    PRD §2.5: "A server's `assigned_table_count` is the number of `SeatTable` rows
    whose `assigned_server_id` is that server and whose `status` is not `RETIRED`".

    Design: Difficulty/compensating_invariant/server_load_conserved_on_table_release
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "ServerCons Night", "starts_at": "2026-04-17T03:00:00Z",
                        "ends_at": "2026-04-17T05:00:00Z", "doors_buffer_minutes": 30},
        server_overrides={"name": "Ivy", "max_tables": 4},
    )
    server_id = sc["server"]["id"]
    before = validate_success(api.get_server(server_id, FLOOR))
    assert before["assigned_table_count"] == 1, "precondition: server owns T1"
    res = create_table_reservation_assigned(sc, patron_id="patron-kk", party_size=2)
    # Past starts_at + doors buffer.
    set_clock("2026-04-17T03:45:00Z")
    no_showed = validate_success(api.no_show(res["id"], FLOOR))
    assert no_showed["booking_status"] == "NO_SHOW", \
        f"expected NO_SHOW, got {no_showed['booking_status']}"
    table = validate_success(api.get_table(sc["table"]["id"], FLOOR))
    assert table["status"] == "AVAILABLE", \
        f"table must be freed to AVAILABLE, got {table['status']}"
    after = validate_success(api.get_server(server_id, FLOOR))
    assert after["assigned_table_count"] == 1, \
        f"server load must be conserved at 1, got {after['assigned_table_count']}"


def test_freed_table_reusable_by_new_reservation_after_no_show(api):
    """PRD §3.7: "sets `booking_status` to `NO_SHOW`, retains the ticket charge
    with no refund so `refunded_cents` is zero, and releases any held table back
    to `AVAILABLE`."
    PRD §3.6: "a table that is not currently `AVAILABLE` — already `HELD`,
    `OCCUPIED`, or `RETIRED` ... is rejected with `ERR_TABLE_UNAVAILABLE`."

    Design: Difficulty/compensating_invariant/server_load_conserved_on_table_release
    """
    sc = setup_table_show_on_sale(
        seats=4, price_cents=4500,
        show_overrides={"title": "Reuse Night", "starts_at": "2026-04-17T03:00:00Z",
                        "ends_at": "2026-04-17T05:00:00Z", "doors_buffer_minutes": 30},
        server_overrides={"name": "Ivy", "max_tables": 4},
    )
    res = create_table_reservation_assigned(sc, patron_id="patron-kk2", party_size=2)
    set_clock("2026-04-17T03:45:00Z")
    no_showed = validate_success(api.no_show(res["id"], FLOOR))
    assert no_showed["refunded_cents"] == 0, \
        f"no-show retains charge, refunded_cents must be 0, got {no_showed['refunded_cents']}"
    # The freed table (AVAILABLE, server still assigned) can hold a new reservation.
    res2 = create_table_reservation(sc, patron_id="patron-kk3", party_size=2)
    table_after = validate_success(api.get_table(sc["table"]["id"], FLOOR))
    reassigned = validate_success(
        api.assign_table(
            res2["id"],
            {"table_id": sc["table"]["id"], "expected_table_version": table_after["version"]},
            FLOOR,
        )
    )
    assert reassigned["table_id"] == sc["table"]["id"], \
        "the released table must be reusable by a new reservation"


# ---------------------------------------------------------------------------
# Corner B — state_machines: cancel voids tickets / double-cancel invalid
# ---------------------------------------------------------------------------
def test_cancel_voids_issued_tickets(api):
    """PRD §3.7: "It also voids every ticket of the reservation that is currently
    `ISSUED` or `SCANNED` (moving them to `VOID`)".

    Design: Corner/state_machines/cancel_voids_issued_tickets
    """
    sc = setup_ga_show_on_sale()
    res = reservation_collected(sc, patron_id="patron-vd", party_size=2)
    validate_success(api.cancel_reservation(res["id"], BOX_OFFICE))
    tickets, meta = validate_paginated(api.list_tickets(BOX_OFFICE, params={"reservation_id": res["id"]}))
    assert meta["total_count"] == 2, f"expected 2 tickets, got {meta['total_count']}"
    for t in tickets:
        assert t["scan_state"] == "VOID", \
            f"every ticket must be VOID after cancel, got {t['scan_state']}"


def test_cancel_already_cancelled_reservation_invalid_state(api):
    """PRD §3.7: "A `BoxOffice` operator or the owning `Patron` may cancel a
    reservation while the show is not yet `SETTLED`, from `booking_status`
    `BOOKED`, `SEATED`, or `CHECKED_IN`."

    Design: Corner/state_machines/cancel_already_cancelled_reservation_invalid_state
    """
    sc = setup_ga_show_on_sale()
    res = create_ga_reservation(sc, patron_id="patron-dx", party_size=1)
    validate_success(api.cancel_reservation(res["id"], BOX_OFFICE))
    resp = api.cancel_reservation(res["id"], BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
