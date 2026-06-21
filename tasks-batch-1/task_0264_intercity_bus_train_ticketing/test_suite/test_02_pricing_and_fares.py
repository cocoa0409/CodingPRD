"""Dynamic per-leg pricing: demand tiers, advance-window tiers, surcharge stacking,
per-leg rounding then summation, and the cash-vs-pass fare divergence.

Traces queue-A `combinatorial_formula`, `dual_variant_calc`
(leg_fare_cash_vs_pass_funded_zero), and `boundary_precision_check`
(load_factor_tier_boundary_at_exactly_half) plus queue-B `calculations`.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    make_passenger_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _only_leg(booking_id, passenger_id):
    legs = fx.legs_for_booking(booking_id, passenger_id)
    assert len(legs) == 1, f"expected single leg, got {len(legs)}"
    return legs[0]


# ─── combinatorial_formula: mode (a) — load-factor x advance x surcharge ──
def test_leg_fare_mid_demand_tier_at_load_factor_half(api):
    """PRD §3.4: "If that load factor is below 0.5 the demand multiplier is 1.00; if
    it is at least 0.5 but below 0.8 the multiplier is 1.25; and if it is at least 0.8
    the multiplier is 1.60 (each tier is lower-inclusive)."
    PRD §3.4: "if it is at least 7 but fewer than 14 the factor is 1.00".

    seats_total=2 with 1 confirmed => load_factor 0.5 => 1.25; departure 2026-06-11 is
    10 days from clock 2026-06-01 => advance 1.00; ECONOMY surcharge 0.
    raw = 4000 * 1.25 * 1.00 = 5000.

    Design: Difficulty/combinatorial_formula/leg_fare_nested_tier_branch_mode_a
    """
    cat = fx.setup_service_date_at_load_factor(
        num_confirmed=1, seats_total=2, base_fare_cents=4000, departure_date="2026-06-11"
    )
    test_p = cat["test_passenger"]
    booking = fx.hold_and_confirm(test_p["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = _only_leg(booking["id"], test_p["id"])
    assert leg["fare_cents"] == 5000, f"expected 5000 (4000*1.25*1.00), got {leg['fare_cents']}"
    assert booking["total_fare_cents"] == 5000


def test_leg_fare_low_demand_tier_below_half(api):
    """PRD §3.4: "If that load factor is below 0.5 the demand multiplier is 1.00".
    PRD §3.4: "if that difference is at least 14 days the factor is 0.90".

    seats_total=10 with 0 confirmed => load_factor 0.0 (< 0.5) => 1.00; departure
    2026-06-15 is 14 days out => advance 0.90; raw = 4000 * 1.00 * 0.90 = 3600.

    Design: Difficulty/combinatorial_formula/leg_fare_nested_tier_branch_mode_a
    """
    cat = fx.setup_catalog(
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000, "departure_date": "2026-06-15"}
    )
    passenger = fx.create_passenger()
    booking = fx.hold_and_confirm(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = _only_leg(booking["id"], passenger["id"])
    assert leg["fare_cents"] == 3600, f"expected 3600 (4000*1.00*0.90), got {leg['fare_cents']}"


# ─── combinatorial_formula: mode (b) — per-leg round then sum ──
def test_total_fare_rounds_each_leg_before_summing(api):
    """PRD §2.7: "Rounding is therefore applied per leg, before the surcharge, and a
    booking total is formed by summing the already-rounded per-leg cents — the
    summation itself is exact."
    PRD §3.4: "The booking's `total_fare_cents` is the sum of the `fare_cents` of all
    `ACTIVE` legs — each leg already rounded — summed exactly".

    Two legs each raw 3333*1.25*0.90 = 3749.625 -> round to 3750; 3750+3750 = 7500
    (NOT 7499 from sum-raw-then-round-once).

    Design: Difficulty/combinatorial_formula/total_fare_per_leg_round_then_sum_mode_b
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL", default_connection_buffer_min=30)
    fare_class = fx.create_fare_class(operator["id"])
    route1 = fx.create_published_route(
        operator["id"], origin_code="NYP", destination_code="PHL",
        depart_minute_of_day=540, arrive_minute_of_day=600,
    )
    route2 = fx.create_published_route(
        operator["id"], origin_code="PHL", destination_code="WAS",
        depart_minute_of_day=700, arrive_minute_of_day=820,
    )
    sd1 = fx.create_service_date(route1["id"], seats_total=2, base_fare_cents=3333, departure_date="2026-06-15")
    sd2 = fx.create_service_date(route2["id"], seats_total=2, base_fare_cents=3333, departure_date="2026-06-15")
    # Pre-confirm one seat on each SD so each has load_factor 0.5 (demand 1.25).
    fx.prefill_confirmed_seats(sd1["id"], fare_class["id"], 1, email_prefix="seed1")
    fx.prefill_confirmed_seats(sd2["id"], fare_class["id"], 1, email_prefix="seed2")

    test_p = fx.create_passenger(full_name="Test Buyer", email="test@x.com")
    legs = [
        f.leg_payload(sd1["id"], fare_class["id"], leg_order=1),
        f.leg_payload(sd2["id"], fare_class["id"], leg_order=2),
    ]
    booking = fx.hold_booking(test_p["id"], None, None, legs=legs)
    confirmed = fx.confirm_booking(booking["id"], test_p["id"], sd1["id"])

    leg_objs = fx.legs_for_booking(booking["id"], test_p["id"])
    assert len(leg_objs) == 2
    for leg in leg_objs:
        assert leg["fare_cents"] == 3750, f"expected each leg 3750, got {leg['fare_cents']}"
    assert confirmed["total_fare_cents"] == 7500, (
        f"expected total 7500 (per-leg round then sum, NOT 7499), got {confirmed['total_fare_cents']}"
    )


def test_total_fare_single_leg_equals_its_leg_fare(api):
    """PRD §3.4: "for a cash booking it is the sum of the per-leg fares".
    PRD §2.7: "a booking total is formed by summing the already-rounded per-leg cents".

    A single ECONOMY leg at load_factor 0 and 14 days out prices to 3600; the
    booking total equals that single rounded leg fare.

    Design: Difficulty/combinatorial_formula/total_fare_per_leg_round_then_sum_mode_b
    """
    cat = fx.setup_catalog(
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000, "departure_date": "2026-06-15"}
    )
    passenger = fx.create_passenger()
    booking = fx.hold_and_confirm(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = _only_leg(booking["id"], passenger["id"])
    assert booking["total_fare_cents"] == leg["fare_cents"] == 3600


# ─── combinatorial_formula: mode (c) — exchange amount pinned eval order ──
def test_exchange_amount_pinned_evaluation_order(api):
    """PRD §3.8: "Step one computes the new leg's fare against the target service date
    using the same per-leg pricing as a fresh confirm (fresh demand and advance
    factors, independent of the old booking). Step two sets the amount due to the new
    leg's fare minus the old booking's `total_paid_cents` plus the operator's
    `exchange_fee_cents`."
    PRD §3.4: "otherwise (fewer than 3 days out) the factor is 1.40".

    Old booking paid 3600. Target SD departs 2026-06-03, 2 days from clock 2026-06-01
    => advance 1.40, load_factor 0 => demand 1.00 => new_leg_fare = 4000*1.00*1.40 = 5600.
    amount_due = 5600 - 3600 + 1000 = 3000. New booking is CONFIRMED + PAID at 5600.

    Design: Difficulty/combinatorial_formula/exchange_amount_pinned_eval_order_mode_c
    """
    s = fx.setup_exchange_ready(
        base_fare_cents=4000, exchange_fee_cents=1000,
        origin_departure="2026-06-15", target_departure="2026-06-03",
    )
    passenger = s["passenger"]
    booking = s["booking"]
    assert booking["total_paid_cents"] == 3600
    b_v = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))["version"]

    resp = api.exchange_booking(
        booking["id"],
        f.exchange_payload(s["target_service_date"]["id"], s["fare_class"]["id"], b_v),
        make_passenger_headers(passenger["id"]),
    )
    new_booking = validate_success(resp, 200)
    old = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert old["booking_status"] == "EXCHANGED"
    assert new_booking["total_fare_cents"] == 5600, (
        f"expected new fare 5600 (4000*1.00*1.40), got {new_booking['total_fare_cents']}"
    )
    assert new_booking["booking_status"] == "CONFIRMED"
    assert new_booking["payment_status"] == "PAID"


def test_exchange_old_booking_terminal_and_tickets_voided(api):
    """PRD §3.8: "moving the old booking's `booking_status` from `CONFIRMED` to the
    terminal `EXCHANGED`".
    PRD §3.2/§3.9: voiding requires the ticket to be `ISSUED`; on exchange "the old
    booking's tickets are voided and a fresh ticket is issued for the new booking".

    Design: Difficulty/combinatorial_formula/exchange_amount_pinned_eval_order_mode_c
    """
    s = fx.setup_exchange_ready(
        base_fare_cents=4000, exchange_fee_cents=1000,
        origin_departure="2026-06-15", target_departure="2026-06-03",
    )
    passenger = s["passenger"]
    booking = s["booking"]
    old_tickets = fx.tickets_for_booking(booking["id"])
    assert len(old_tickets) == 1 and old_tickets[0]["state"] == "ISSUED"
    b_v = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))["version"]

    resp = api.exchange_booking(
        booking["id"],
        f.exchange_payload(s["target_service_date"]["id"], s["fare_class"]["id"], b_v),
        make_passenger_headers(passenger["id"]),
    )
    validate_success(resp, 200)
    old_tickets_after = fx.tickets_for_booking(booking["id"])
    assert all(t["state"] == "VOID" for t in old_tickets_after), "old tickets must be VOID after exchange"


# ─── dual_variant_calc: cash leg vs pass-funded zero ──
def test_cash_leg_priced_pass_leg_zero(api):
    """PRD §3.4: "For a pass-funded booking there is no demand or advance math at all:
    `fare_cents` is 0 on every leg, and one travel-pass ride is consumed per leg
    instead. The booking's `total_fare_cents` is the sum of the `fare_cents` of all
    `ACTIVE` legs ... for a pass booking the total is 0."

    A CASH leg on the SD (load_factor 0, 14 days out) prices to 3600; a PASS leg on
    the same SD prices to 0.

    Design: Difficulty/dual_variant_calc/leg_fare_cash_vs_pass_funded_zero
    """
    cat = fx.setup_catalog(
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000, "departure_date": "2026-06-15"}
    )
    passenger = fx.create_passenger()
    travel_pass = fx.create_pass(passenger["id"], cat["operator"]["id"], rides_total=10)

    cash_booking = fx.hold_and_confirm(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    cash_leg = _only_leg(cash_booking["id"], passenger["id"])
    assert cash_leg["fare_cents"] == 3600
    assert cash_booking["total_fare_cents"] == 3600

    pass_booking = fx.hold_and_confirm(
        passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"],
        funding_kind="PASS", pass_id=travel_pass["id"],
    )
    pass_leg = _only_leg(pass_booking["id"], passenger["id"])
    assert pass_leg["fare_cents"] == 0, f"PASS leg fare must be 0, got {pass_leg['fare_cents']}"
    assert pass_booking["total_fare_cents"] == 0


def test_pass_funded_confirm_consumes_one_ride(api):
    """PRD §3.4: "one travel-pass ride is consumed per leg instead."
    PRD §3.10: "A pass-funded booking confirm consumes one ride per leg" and
    "`rides_remaining`, which is `rides_total` minus `rides_consumed`".

    A single-leg PASS confirm against a rides_total=10 pass leaves
    rides_consumed 1, rides_remaining 9.

    Design: Difficulty/dual_variant_calc/leg_fare_cash_vs_pass_funded_zero
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10})
    passenger = fx.create_passenger()
    travel_pass = fx.create_pass(passenger["id"], cat["operator"]["id"], rides_total=10)
    fx.hold_and_confirm(
        passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"],
        funding_kind="PASS", pass_id=travel_pass["id"],
    )
    after = get_success_data(api.get_pass(travel_pass["id"], make_passenger_headers(passenger["id"])))
    assert after["rides_consumed"] == 1
    assert after["rides_remaining"] == 9


# ─── boundary_precision_check: load_factor exactly 0.5 ──
def test_load_factor_exactly_half_selects_mid_tier(api):
    """PRD §3.4: "if it is at least 0.5 but below 0.8 the multiplier is 1.25 ... (each
    tier is lower-inclusive)."
    PRD §3.4: "if that difference is at least 14 days the factor is 0.90".

    seats_total=2 with 1 confirmed => load_factor exactly 0.5 => 1.25; 14 days out
    => 0.90; raw = 4000 * 1.25 * 0.90 = 4500 (NOT 3600 of the 1.00 tier).

    Design: Difficulty/boundary_precision_check/load_factor_tier_boundary_at_exactly_half
    """
    cat = fx.setup_service_date_at_load_factor(
        num_confirmed=1, seats_total=2, base_fare_cents=4000, departure_date="2026-06-15"
    )
    test_p = cat["test_passenger"]
    booking = fx.hold_and_confirm(test_p["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = _only_leg(booking["id"], test_p["id"])
    assert leg["fare_cents"] == 4500, (
        f"load_factor 0.5 must select 1.25 tier (4000*1.25*0.90=4500), got {leg['fare_cents']}"
    )


def test_load_factor_below_half_selects_low_tier(api):
    """PRD §3.4: "If that load factor is below 0.5 the demand multiplier is 1.00".
    PRD §3.4: "if that difference is at least 14 days the factor is 0.90".

    seats_total=3 with 1 confirmed => load_factor 1/3 ≈ 0.333 (< 0.5) => 1.00; 14 days
    out => 0.90; raw = 4000 * 1.00 * 0.90 = 3600 (low tier, not the 0.5 boundary tier).

    Design: Difficulty/boundary_precision_check/load_factor_tier_boundary_at_exactly_half
    """
    cat = fx.setup_service_date_at_load_factor(
        num_confirmed=1, seats_total=3, base_fare_cents=4000, departure_date="2026-06-15"
    )
    test_p = cat["test_passenger"]
    booking = fx.hold_and_confirm(test_p["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = _only_leg(booking["id"], test_p["id"])
    assert leg["fare_cents"] == 3600, (
        f"load_factor 1/3 < 0.5 must select 1.00 tier (4000*1.00*0.90=3600), got {leg['fare_cents']}"
    )


# ─── calculations (corner) ────────────────────────────
def test_advance_window_boundary_at_14_days(api):
    """PRD §3.4: "if that difference is at least 14 days the factor is 0.90".

    Departure 2026-06-15 is exactly 14 days from clock 2026-06-01 => advance 0.90;
    load_factor 0 => demand 1.00; raw = 4000 * 1.00 * 0.90 = 3600.

    Design: Corner/calculations/advance_window_boundary_at_14_days
    """
    cat = fx.setup_catalog(
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000, "departure_date": "2026-06-15"}
    )
    passenger = fx.create_passenger()
    booking = fx.hold_and_confirm(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    leg = _only_leg(booking["id"], passenger["id"])
    assert leg["fare_cents"] == 3600, (
        f"exactly 14 days out must select 0.90 (4000*1.00*0.90=3600), got {leg['fare_cents']}"
    )


def test_business_surcharge_stacks_after_multipliers(api):
    """PRD §2.7: "the resulting raw product is rounded half up to whole cents, and
    only then is the fare class's flat surcharge added."
    PRD §3.4: "if it is at least 0.8 the multiplier is 1.60" and "if that difference is
    at least 14 days the factor is 0.90".

    seats_total=5 with 4 confirmed => load_factor 0.8 => 1.60; 14 days out => 0.90;
    base 6000 => round(6000*1.60*0.90)=8640; + 1500 surcharge = 10140.

    Design: Corner/calculations/high_demand_business_surcharge_stacking
    """
    cat = fx.setup_service_date_at_load_factor(
        num_confirmed=4, seats_total=5, base_fare_cents=6000, departure_date="2026-06-15",
        reserved=True, fare_overrides={"code": "BUSINESS", "seating_mode": "RESERVED", "surcharge_cents": 1500},
        operator_overrides={"mode": "RAIL"},
    )
    test_p = cat["test_passenger"]
    booking = fx.hold_and_confirm(
        test_p["id"], cat["service_date"]["id"], cat["fare_class"]["id"], seat_number="1E"
    )
    leg = _only_leg(booking["id"], test_p["id"])
    assert leg["fare_cents"] == 10140, (
        f"expected 10140 (round(6000*1.60*0.90)=8640 + 1500), got {leg['fare_cents']}"
    )
