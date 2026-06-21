"""Cross-entity cascades and conservation invariants.

Covers Difficulty rules transitive_cascade (no-show → capture → strike → block →
mass-cancel; late-cancel → free table → promote waitlist) and
compensating_invariant (funds conserved on hold→release; slot conserved on
book→cancel), plus the buyout-cascade corner instance.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data, make_customer_headers, TEST_USERS,
    setup_floor, setup_confirmed_reservation,
    book_reservation, confirm, place_hold, set_clock, join_waitlist,
    make_restaurant, make_dining_area, make_table, make_service_period,
    make_customer, make_private_event, propose_private_event, confirm_private_event,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── transitive_cascade / noshow → capture → strike → block → mass-cancel ──
def _setup_noshow_block_scenario(api):
    """A restaurant with no_show_strike_block_threshold 1; one CONFIRMED held
    party-6 reservation about to be no-showed, plus a separate future CONFIRMED
    reservation the resulting block must cancel. Returns ids dict."""
    floor = setup_floor(
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6,
                              "no_show_strike_block_threshold": 1,
                              "late_cancel_cutoff_hours": 24},
        table_overrides={"max_party_size": 8, "label": "T1"},
        period_overrides={"pacing_max_covers_per_slot": 30})
    rid, cust = floor["restaurant"]["id"], floor["customer"]["id"]
    tbl1 = floor["table"]["id"]
    tbl2 = get_success_data(api.create_table(
        {"dining_area_id": floor["area"]["id"], "label": "T2",
         "min_party_size": 1, "max_party_size": 8}, MANAGER))["id"]
    res_x = book_reservation(rid, cust, tbl1, party_size=6,
                             reservation_start="2026-06-15T18:00:00Z")
    hold_x = place_hold(res_x["id"], cust)
    confirm(res_x["id"])
    res_future = book_reservation(rid, cust, tbl2, party_size=4,
                                  reservation_start="2026-06-16T18:00:00Z")
    confirm(res_future["id"])
    return {"res_x": res_x["id"], "hold_x": hold_x["id"], "res_future": res_future["id"],
            "cust": cust}


def test_noshow_captures_deposit_and_strikes_block_customer(api):
    """PRD §3.5: "If the increment brings `no_show_strikes` to or above the
    restaurant's `no_show_strike_block_threshold`, the customer is set
    `BLOCKED`".

    Design: Difficulty/transitive_cascade/noshow_capture_strike_block_masscancel_depth4
    """
    ids = _setup_noshow_block_scenario(api)
    set_clock("2026-06-15T18:20:00Z")
    validate_success(api.no_show_reservation(ids["res_x"], HOST), 200)
    hold = validate_success(api.get_deposit_hold(ids["hold_x"], MANAGER), 200)
    assert hold["status"] == "CAPTURED" and hold["captured_cents"] == 15000
    customer = validate_success(api.get_customer(ids["cust"], HOST), 200)
    assert customer["no_show_strikes"] == 1
    assert customer["status"] == "BLOCKED"


def test_noshow_block_mass_cancels_future_reservation(api):
    """PRD §3.2: "Blocking sets the customer's status to `BLOCKED` and cascades:
    for every reservation of that customer that is `CONFIRMED` or `REQUESTED`
    with a start in the future, the reservation is set `CANCELLED`".

    Design: Difficulty/transitive_cascade/noshow_capture_strike_block_masscancel_depth4
    """
    ids = _setup_noshow_block_scenario(api)
    set_clock("2026-06-15T18:20:00Z")
    validate_success(api.no_show_reservation(ids["res_x"], HOST), 200)
    future = validate_success(api.get_reservation(ids["res_future"], HOST), 200)
    assert future["status"] == "CANCELLED", \
        "the block cascade mass-cancels the future CONFIRMED reservation"


# ─── transitive_cascade / late-cancel → free table → promote waitlist ──────
def _setup_cancel_promote_scenario(api):
    """A CONFIRMED reservation occupying the only table, plus a WAITING entry
    whose party fits; 2h cutoff so a 6h-out cancel is early (fee 0)."""
    floor = setup_floor(
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "late_cancel_cutoff_hours": 2},
        table_overrides={"max_party_size": 4})
    rid = floor["restaurant"]["id"]
    cust1 = floor["customer"]["id"]
    tbl = floor["table"]["id"]
    cust2 = get_success_data(api.create_customer(
        {"full_name": "Ivan", "phone": "+19998880001"}))["id"]
    res = book_reservation(rid, cust1, tbl, party_size=2,
                           reservation_start="2026-06-15T18:00:00Z")
    confirm(res["id"])
    wl = join_waitlist(rid, cust2, party_size=2,
                       requested_start="2026-06-15T18:00:00Z")
    return {"res": res["id"], "wl": wl["id"], "cust1": cust1}


def test_early_cancel_charges_no_fee(api):
    """PRD §3.6: "Cancelling a `CONFIRMED` reservation computes the cancellation
    fee per §3.5: if the fee is greater than zero it captures that amount on any
    `HELD` hold ... and if the fee is zero it releases the hold instead."

    Design: Difficulty/transitive_cascade/late_cancel_release_freetable_promote_waitlist_depth2
    """
    ids = _setup_cancel_promote_scenario(api)
    # Clock 12:00, start 18:00, cutoff 2h → 6h out → early → fee 0.
    res = validate_success(
        api.cancel_reservation(ids["res"], make_customer_headers(ids["cust1"])), 200)
    assert res["status"] == "CANCELLED"
    assert res["cancellation_fee_cents"] == 0, "6h-out cancel with 2h cutoff is early (fee 0)"


def test_cancel_frees_table_and_notifies_waitlist(api):
    """PRD §3.6: "unless the table is currently `SEATED`, the freeing triggers
    the table-freeing cascade that promotes and notifies the next eligible
    waitlist party."

    Design: Difficulty/transitive_cascade/late_cancel_release_freetable_promote_waitlist_depth2
    """
    ids = _setup_cancel_promote_scenario(api)
    validate_success(
        api.cancel_reservation(ids["res"], make_customer_headers(ids["cust1"])), 200)
    entry = validate_success(api.get_waitlist_entry(ids["wl"], HOST), 200)
    assert entry["status"] == "NOTIFIED", \
        "freed table promotes the waiting party to NOTIFIED"


# ─── compensating_invariant / funds conserved on hold → early-cancel ───────
def test_hold_then_early_cancel_conserves_funds(api):
    """PRD §3.6: "if the fee is zero it releases the hold instead." PRD §3.9:
    "It reaches `RELEASED` ... which sets `captured_cents` to 0 and the hold
    `RELEASED`."

    Design: Difficulty/compensating_invariant/deposit_funds_conserved_hold_then_release
    """
    ctx = setup_confirmed_reservation(
        party_size=6, deposit=True,
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6,
                              "late_cancel_cutoff_hours": 2},
        table_overrides={"max_party_size": 8})
    assert ctx["hold"]["amount_cents"] == 15000
    res = validate_success(
        api.cancel_reservation(ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    assert res["cancellation_fee_cents"] == 0
    hold = validate_success(api.get_deposit_hold(ctx["hold"]["id"], MANAGER), 200)
    assert hold["captured_cents"] == 0, "net captured stays 0 after hold then release"
    assert hold["status"] == "RELEASED"


def test_hold_amount_unchanged_by_release(api):
    """PRD §3.4: "computes the held `amount_cents` as the restaurant's
    `per_seat_deposit_cents` multiplied by the reservation's `party_size`".

    Design: Difficulty/compensating_invariant/deposit_funds_conserved_hold_then_release
    """
    ctx = setup_confirmed_reservation(
        party_size=6, deposit=True,
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6,
                              "late_cancel_cutoff_hours": 2},
        table_overrides={"max_party_size": 8})
    validate_success(
        api.cancel_reservation(ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    hold = validate_success(api.get_deposit_hold(ctx["hold"]["id"], MANAGER), 200)
    # The held amount records what was authorized; release zeroes captured, not amount.
    assert hold["amount_cents"] == 15000


# ─── compensating_invariant / slot conserved on book → cancel → re-book ────
def test_cancel_frees_slot_for_rebooking_same_table(api):
    """PRD §3.6: "Cancelling a `REQUESTED` reservation simply sets it
    `CANCELLED` and releases any `HELD` hold with no fee". PRD §3.3: "The new
    window must not intersect the window of any active reservation on the same
    `table_id`; an intersection is rejected with `ERR_TABLE_DOUBLE_BOOKED`."

    Design: Difficulty/compensating_invariant/table_slot_availability_conserved_book_then_cancel
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    res1 = book_reservation(rid, cust, tbl, party_size=2,
                            reservation_start="2026-06-15T18:00:00Z")
    validate_success(
        api.cancel_reservation(res1["id"], make_customer_headers(cust)), 200)
    # Slot freed → a fresh 18:00 booking on the same table must succeed.
    res2 = book_reservation(rid, cust, tbl, party_size=2,
                            reservation_start="2026-06-15T18:00:00Z")
    assert res2["status"] == "REQUESTED", "freed slot is re-bookable"


def test_cancelled_reservation_is_terminal_cancelled(api):
    """PRD §3.6: "In all cases the reservation is set `CANCELLED`".

    Design: Difficulty/compensating_invariant/table_slot_availability_conserved_book_then_cancel
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    res1 = book_reservation(rid, cust, tbl, party_size=2,
                            reservation_start="2026-06-15T18:00:00Z")
    validate_success(
        api.cancel_reservation(res1["id"], make_customer_headers(cust)), 200)
    after = validate_success(api.get_reservation(res1["id"], HOST), 200)
    assert after["status"] == "CANCELLED"


# ─── corner / buyout confirm cascades cancel intersecting reservations ─────
def test_buyout_confirm_cancels_intersecting_reservation_releases_hold(api):
    """PRD §3.4: "every `CONFIRMED` or `REQUESTED` reservation whose `table_id`
    belongs to this dining area and whose own window from `reservation_start` up
    to `release_at` intersects the buyout window from `event_start` to
    `event_end` is cancelled, and each such reservation's `HELD` deposit hold is
    released; the event becomes `CONFIRMED`."

    Design: Corner/cross_cutting_complexity_layers/buyout_confirm_cascades_cancel_intersecting_reservations
    """
    ctx = setup_private_area_with_table_and_reservation(api)
    event = ctx["event"]
    confirmed = confirm_private_event(event["id"], ctx["area_version"])
    assert confirmed["status"] == "CONFIRMED"
    area = validate_success(api.get_dining_area(ctx["area"]["id"], HOST), 200)
    assert area["status"] == "BOUGHT_OUT"
    res = validate_success(api.get_reservation(ctx["res"], HOST), 200)
    assert res["status"] == "CANCELLED", "intersecting reservation is cancelled by the buyout"
    hold = validate_success(api.get_deposit_hold(ctx["hold"], MANAGER), 200)
    assert hold["status"] == "RELEASED", "the cancelled reservation's hold is released"


def setup_private_area_with_table_and_reservation(api):
    """PRIVATE area + table; a party-6 CONFIRMED reservation at 19:00 with a HELD
    deposit; a PROPOSED buyout over [18:00, 22:00]. Returns ctx dict."""
    restaurant = make_restaurant(per_seat_deposit_cents=2500,
                                 deposit_required_party_threshold=6)
    area = make_dining_area(restaurant["id"], name="PRIVATE_ROOM", kind="PRIVATE")
    area_version = area["version"]
    table = make_table(area["id"], label="P1", max_party_size=8)
    make_service_period(restaurant["id"], pacing_max_covers_per_slot=30)
    customer = make_customer()
    set_clock("2026-06-15T12:00:00Z")
    res = book_reservation(restaurant["id"], customer["id"], table["id"],
                           party_size=6, reservation_start="2026-06-15T19:00:00Z")
    hold = place_hold(res["id"], customer["id"])
    confirm(res["id"])
    event = make_private_event(restaurant["id"], area["id"], customer["id"],
                               party_size=8, food_minimum_cents=200000,
                               event_start="2026-06-15T18:00:00Z",
                               event_end="2026-06-15T22:00:00Z")
    propose_private_event(event["id"])
    return {"area": area, "area_version": area_version, "res": res["id"],
            "hold": hold["id"], "event": event}
