"""Deposit and reliability calculations — the two dual-variant calc families
and the combinatorial cancellation-fee / private-dining-deposit formulas.

Covers Difficulty rules dual_variant_calc and combinatorial_formula, plus the
corner calculations that are not owned by an excluded_because stub.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data, make_customer_headers,
    TEST_USERS,
    create_private_dining_event_payload, create_deposit_hold_payload,
    create_reservation_payload,
    setup_floor, setup_private_area, setup_confirmed_reservation,
    make_restaurant, make_dining_area, make_table, make_service_period,
    make_customer, set_clock, book_reservation, place_hold, confirm,
    make_private_event, propose_private_event,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── dual_variant_calc / deposit_per_seat_vs_private_dining_percentage ─────
def test_standard_deposit_is_per_seat_product(api):
    """PRD §3.4: "computes the held `amount_cents` as the restaurant's
    `per_seat_deposit_cents` multiplied by the reservation's `party_size` — an
    exact integer product."

    Design: Difficulty/dual_variant_calc/deposit_per_seat_vs_private_dining_percentage
    """
    floor = setup_floor(restaurant_overrides={"per_seat_deposit_cents": 2500,
                                              "deposit_required_party_threshold": 6},
                        table_overrides={"max_party_size": 8})
    res = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                           floor["table"]["id"], party_size=6)
    hold = place_hold(res["id"], floor["customer"]["id"])
    assert hold["amount_cents"] == 15000, \
        f"per-seat deposit 2500 * 6 == 15000, got {hold['amount_cents']}"


def test_private_dining_deposit_is_percentage_of_food_minimum(api):
    """PRD §3.4: "the food component is `food_minimum_cents` multiplied by
    `deposit_pct`, rounded half up to a whole cent ... and `deposit_due_cents`
    is the food component plus the service component."

    Design: Difficulty/dual_variant_calc/deposit_per_seat_vs_private_dining_percentage
    """
    ctx = setup_private_area()
    event = make_private_event(ctx["restaurant"]["id"], ctx["area"]["id"],
                               ctx["customer"]["id"],
                               food_minimum_cents=400000, deposit_pct=0.25,
                               event_start="2026-06-20T18:00:00Z",
                               event_end="2026-06-20T22:00:00Z")
    proposed = propose_private_event(event["id"])
    assert proposed["deposit_due_cents"] == 100000, \
        f"food 400000 * 0.25 == 100000, got {proposed['deposit_due_cents']}"


# ─── dual_variant_calc / reliability_settled_vs_provisional_projection ─────
def _setup_one_failure_one_open(api):
    """A customer with one NO_SHOW (1 failure, 0 completed) and one currently
    CONFIRMED future reservation (1 open). Returns the customer id."""
    floor = setup_floor(restaurant_overrides={"per_seat_deposit_cents": 2500,
                                              "no_show_strike_block_threshold": 3})
    rid = floor["restaurant"]["id"]
    cust = floor["customer"]["id"]
    tbl = floor["table"]["id"]
    # First reservation → confirm → no-show after grace (1 failure).
    res_a = book_reservation(rid, cust, tbl, party_size=2,
                             reservation_start="2026-06-15T18:00:00Z")
    confirm(res_a["id"])
    set_clock("2026-06-15T18:20:00Z")
    get_success_data(api.no_show_reservation(res_a["id"], HOST))
    # Second reservation (future) → confirm → leaves 1 open CONFIRMED.
    res_b = book_reservation(rid, cust, tbl, party_size=2,
                             reservation_start="2026-06-16T18:00:00Z")
    confirm(res_b["id"])
    return cust


def test_settled_reliability_zero_after_one_no_show(api):
    """PRD §3.2: "if that denominator is zero the score is 100.0, otherwise the
    score is one hundred multiplied by `lifetime_reservations` divided by that
    denominator, rounded half up to one decimal place."

    Design: Difficulty/dual_variant_calc/reliability_settled_vs_provisional_projection
    """
    cust = _setup_one_failure_one_open(api)
    data = validate_success(api.get_customer_reliability(cust, HOST), 200)
    assert data["reliability_pct"] == 0.0, \
        f"settled = 100*0/(0+1) == 0.0, got {data['reliability_pct']}"
    assert data["lifetime_failures"] == 1
    assert data["lifetime_reservations"] == 0


def test_provisional_reliability_projects_open_confirmed_as_success(api):
    """PRD §3.2: "both the numerator and the denominator add the count of those
    open confirmed bookings, so the projected score generally differs from the
    settled score for the same guest."

    Design: Difficulty/dual_variant_calc/reliability_settled_vs_provisional_projection
    """
    cust = _setup_one_failure_one_open(api)
    data = validate_success(
        api.get_customer_reliability(cust, HOST, params={"mode": "provisional"}), 200)
    # numerator 0+1, denominator (0+1)+1 → 100*1/2 == 50.0
    assert data["reliability_pct"] == 50.0, \
        f"provisional = 100*(0+1)/((0+1)+1) == 50.0, got {data['reliability_pct']}"


# ─── combinatorial_formula / cancellation_fee_tiered_three_input_nonlinear ─
def test_late_cancel_50pct_tier_party6(api):
    """PRD §3.5: "if the hours-before-start is greater than or equal to 2 the
    fee is one-half of the per-seat amount times the headcount, rounded half up
    to a whole cent".

    Design: Difficulty/combinatorial_formula/cancellation_fee_tiered_three_input_nonlinear
    """
    ctx = setup_confirmed_reservation(
        party_size=6, deposit=True,
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6,
                              "late_cancel_cutoff_hours": 24},
        table_overrides={"max_party_size": 8})
    # 5h before start (inside 24h cutoff, above the 2h tier).
    set_clock("2026-06-15T13:00:00Z")
    res = validate_success(
        api.cancel_reservation(ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    assert res["cancellation_fee_cents"] == 7500, \
        f"0.50 * 2500 * 6 == 7500, got {res['cancellation_fee_cents']}"
    hold = validate_success(api.get_deposit_hold(ctx["hold"]["id"], MANAGER), 200)
    assert hold["captured_cents"] == 7500
    assert hold["status"] == "CAPTURED"


def test_late_cancel_fee_capped_at_held_amount(api):
    """PRD §3.5: "In every case, when a `HELD` deposit hold exists, the fee is
    capped at that hold's `amount_cents` — the captured amount can never exceed
    what was held."

    Design: Difficulty/combinatorial_formula/cancellation_fee_tiered_three_input_nonlinear
    """
    # Party 6, per-seat 2500 → 50% tier fee = 7500, hold amount = 15000 (>= fee),
    # so the cap is inactive and the captured amount equals the computed fee.
    ctx = setup_confirmed_reservation(
        party_size=6, deposit=True,
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6,
                              "late_cancel_cutoff_hours": 24},
        table_overrides={"max_party_size": 8})
    set_clock("2026-06-15T13:00:00Z")
    res = validate_success(
        api.cancel_reservation(ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    hold = validate_success(api.get_deposit_hold(ctx["hold"]["id"], MANAGER), 200)
    assert hold["captured_cents"] == res["cancellation_fee_cents"]
    assert hold["captured_cents"] <= hold["amount_cents"], \
        "captured amount can never exceed what was held"


# ─── combinatorial_formula / private_dining_deposit_round_then_sum_order ───
def test_private_dining_deposit_round_then_sum_two_components(api):
    """PRD §3.4: "The rounding must be applied to each component before they are
    added — summing the two raw products and rounding once is incorrect, because
    the two orders can diverge by a cent."

    Design: Difficulty/combinatorial_formula/private_dining_deposit_round_then_sum_order
    """
    ctx = setup_private_area()
    event = make_private_event(ctx["restaurant"]["id"], ctx["area"]["id"],
                               ctx["customer"]["id"],
                               party_size=20, food_minimum_cents=100003,
                               deposit_pct=0.25, service_charge_pct=0.18,
                               event_start="2026-06-21T18:00:00Z",
                               event_end="2026-06-21T22:00:00Z")
    proposed = propose_private_event(event["id"])
    # round(100003*0.25)=round(25000.75)=25001; round(100003*0.18)=round(18000.54)=18001;
    # round-then-sum = 43002 (sum-then-round would be 43001).
    assert proposed["deposit_due_cents"] == 43002, \
        f"round-then-sum 25001 + 18001 == 43002, got {proposed['deposit_due_cents']}"


def test_private_dining_deposit_service_component_rounded_separately(api):
    """PRD §3.4: "the service component is `food_minimum_cents` multiplied by
    `service_charge_pct`, rounded half up to a whole cent; and `deposit_due_cents`
    is the food component plus the service component."

    Design: Difficulty/combinatorial_formula/private_dining_deposit_round_then_sum_order
    """
    ctx = setup_private_area()
    event = make_private_event(ctx["restaurant"]["id"], ctx["area"]["id"],
                               ctx["customer"]["id"],
                               party_size=20, food_minimum_cents=100003,
                               deposit_pct=0.25, service_charge_pct=0.18,
                               event_start="2026-06-22T18:00:00Z",
                               event_end="2026-06-22T22:00:00Z")
    proposed = propose_private_event(event["id"])
    # food component round(25000.75)=25001; service component round(18000.54)=18001.
    assert proposed["deposit_due_cents"] == 25001 + 18001


# ─── corner calculations (non-stub) ───────────────────────────────────────
def test_no_show_fee_full_per_seat_variant(api):
    """PRD §3.5: "A no-show computes the cancellation fee in its no-show variant
    — always the full per-seat deposit times the party size".

    Design: Corner/calculations/noshow_fee_full_per_seat_variant
    """
    ctx = setup_confirmed_reservation(
        party_size=6, deposit=True,
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6},
        table_overrides={"max_party_size": 8})
    set_clock("2026-06-15T18:20:00Z")
    res = validate_success(api.no_show_reservation(ctx["reservation"]["id"], HOST), 200)
    assert res["cancellation_fee_cents"] == 15000, \
        f"no-show fee 2500 * 6 == 15000, got {res['cancellation_fee_cents']}"
    hold = validate_success(api.get_deposit_hold(ctx["hold"]["id"], MANAGER), 200)
    assert hold["captured_cents"] == 15000
    assert hold["status"] == "CAPTURED"


def test_late_cancel_under_two_hours_full_fee(api):
    """PRD §3.5: "otherwise (less than two hours out) the fee is the full
    per-seat amount times the headcount."

    Design: Corner/calculations/late_cancel_under_two_hours_full_fee
    """
    ctx = setup_confirmed_reservation(
        party_size=6, deposit=True,
        restaurant_overrides={"per_seat_deposit_cents": 2500,
                              "deposit_required_party_threshold": 6,
                              "late_cancel_cutoff_hours": 24},
        table_overrides={"max_party_size": 8})
    # 1h before start (< 2h tier) → full fee.
    set_clock("2026-06-15T17:00:00Z")
    res = validate_success(
        api.cancel_reservation(ctx["reservation"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    assert res["cancellation_fee_cents"] == 15000, \
        f"under-2h fee 2500 * 6 == 15000, got {res['cancellation_fee_cents']}"
    hold = validate_success(api.get_deposit_hold(ctx["hold"]["id"], MANAGER), 200)
    assert hold["captured_cents"] == 15000
    assert hold["status"] == "CAPTURED"
