"""Booking quote and final-settlement arithmetic.

Covers the dual-variant quote-vs-final calculation, the combinatorial surge/weekend
quote, per-line payout rounding, and the corner-design quote/settlement instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    make_driver_headers, make_host_headers, TEST_USERS,
    setup_host_driver_spot, setup_checked_in_booking, checkout_at, set_clock,
    create_booking, register_host, register_driver, fund_driver, create_spot,
    create_pricing_event,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Difficulty: dual_variant_calc / booking_quote_vs_final_settlement_overstay_delta ───

def test_quote_frozen_while_final_recomputes_on_overstay(api):
    """PRD §3.3: "Finally, the quoted amount is the greater of that rounded raw amount
    and the spot's `base_hourly_cents`, so the quote is never below one base hour."
    PRD §3.5: "The final amount is the frozen `quoted_amount_cents` (the base portion is
    the quote, never re-priced) plus an overstay charge."
    PRD §3.5: "the overstay charge is those hours multiplied by the spot's
    `base_hourly_cents` multiplied by 15000 basis points divided by 10000 — that is, the
    overstay is billed at 1.5 times the spot's base hourly rate, never at any surged rate."

    Booking HOURLY [10:00,12:00) at base 400 quotes 800 (2h). Checkout at 13:30 is 75 min
    past end+grace (12:15), so overstay = 75 min -> ceil 2 overstay hours -> 2*400*1.5=1200;
    final = 800 + 1200 = 2000, distinct from the frozen quote of 800.

    Design: Difficulty/dual_variant_calc/booking_quote_vs_final_settlement_overstay_delta
    """
    host, driver, spot, booking = setup_checked_in_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T12:00:00Z",
        spot_overrides={"base_hourly_cents": 400, "overstay_grace_minutes": 15})
    assert booking["quoted_amount_cents"] == 800, booking["quoted_amount_cents"]

    final = checkout_at(driver["id"], booking["id"], "2026-04-08T13:30:00Z")
    assert final["quoted_amount_cents"] == 800
    assert final["final_amount_cents"] == 2000, final["final_amount_cents"]
    assert final["final_amount_cents"] != final["quoted_amount_cents"]


def test_dual_variant_final_differs_from_frozen_quote(api):
    """PRD §3.5: "On checkout the server records `actual_checkout_at` as the logical clock
    and computes `final_amount_cents`."
    PRD §3.3: "`final_amount_cents` is left null until checkout".

    Same booking, two different computed money fields: quoted_amount_cents (frozen 800 at
    creation) and final_amount_cents (2000 at checkout incl. overstay) diverge.

    Design: Difficulty/dual_variant_calc/booking_quote_vs_final_settlement_overstay_delta
    """
    host, driver, spot, booking = setup_checked_in_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T12:00:00Z",
        spot_overrides={"base_hourly_cents": 400, "overstay_grace_minutes": 15})
    assert booking["final_amount_cents"] is None, "final null until checkout"

    final = checkout_at(driver["id"], booking["id"], "2026-04-08T13:30:00Z")
    assert final["final_amount_cents"] == 2000
    assert final["quoted_amount_cents"] == 800


# ─── Difficulty: combinatorial_formula / quote_hourly_surge_weekday_three_input_nonlinear ───

def test_quote_hourly_surge_weekday_nonlinear(api):
    """PRD §3.3: "the duration in seconds is divided by 3600 and rounded up to the next
    whole hour, and that number of hours is multiplied by the spot's `base_hourly_cents`."
    PRD §3.3: "The raw amount is the base multiplied by the surge factor divided by 10000
    and then multiplied by the weekend factor divided by 10000."

    3-hour HOURLY window on a Wednesday (no weekend uplift) at base 400 under a 25000 bps
    surge: 3*400 = 1200, *2.5 = 3000.

    Design: Difficulty/combinatorial_formula/quote_hourly_surge_weekday_three_input_nonlinear
    """
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"base_hourly_cents": 400, "zone_code": "DT-01"}, wallet_cents=5000)
    create_pricing_event("DT-01", "2026-04-08T00:00:00Z", "2026-04-09T00:00:00Z", 25000)
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T13:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 3000, booking["quoted_amount_cents"]


def test_quote_surge_applied_only_to_matching_zone_event(api):
    """PRD §3.3: "among the `ACTIVE` pricing events for the spot's `zone_code` whose
    half-open window from `window_start` (inclusive) to `window_end` (exclusive) contains
    `start_at`, the server selects the single matching event with the highest
    `surge_multiplier_bps` ... or 10000 if no event matches."

    A 3-hour HOURLY booking whose start_at (10:00) sits inside the active 25000 bps event
    window quotes 3000 = 3*400*2.5 (surge applied, weekday so no weekend factor).

    Design: Difficulty/combinatorial_formula/quote_hourly_surge_weekday_three_input_nonlinear
    """
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"base_hourly_cents": 400, "zone_code": "DT-01"}, wallet_cents=5000)
    create_pricing_event("DT-01", "2026-04-08T00:00:00Z", "2026-04-09T00:00:00Z", 25000)
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T13:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 3000


# ─── Difficulty: combinatorial_formula / host_payout_per_line_rounding_order_pinned ───

def test_host_payout_per_line_rounding_two_bookings(api):
    """PRD §3.7: "The platform fee in cents is the gross multiplied by the host's
    `platform_fee_bps` divided by 10000, rounded half up to a whole cent at this
    per-booking step."
    PRD §3.7: "Because the per-booking fee is rounded before being summed into the ledger
    — rounding each booking's fee individually rather than summing gross amounts and
    rounding an aggregate fee — the per-line rounding order is pinned and must not be
    replaced by a sum-then-round approach."

    Two HOURLY bookings each gross 830 at fee 1500 bps: fee per booking = round_half_up(124.5)
    = 125, net 705 each, lifetime = 1410. Sum-then-round would give 1411; pinned order is 1410.

    Design: Difficulty/combinatorial_formula/host_payout_per_line_rounding_order_pinned
    """
    host = register_host(platform_fee_bps=1500)
    driver = register_driver()
    fund_driver(driver["id"], 5000)
    spot = create_spot(host["id"], base_hourly_cents=830, base_daily_cents=20000,
                       monthly_flat_cents=200000, zone_code="Z4", overstay_grace_minutes=15)

    # First booking, on-time check-in/out.
    b1 = create_booking(spot["id"], driver["id"], "HOURLY",
                        "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    sv2 = get_success_data(api.get_spot(spot["id"], make_host_headers(host["id"])))["version"]
    b2 = create_booking(spot["id"], driver["id"], "HOURLY",
                        "2026-04-08T11:00:00Z", "2026-04-08T12:00:00Z", sv2)
    assert b1["quoted_amount_cents"] == 830
    assert b2["quoted_amount_cents"] == 830

    set_clock("2026-04-08T10:00:00Z")
    get_success_data(api.check_in_booking(b1["id"], make_driver_headers(driver["id"])))
    get_success_data(api.check_out_booking(b1["id"], make_driver_headers(driver["id"])))
    set_clock("2026-04-08T11:00:00Z")
    get_success_data(api.check_in_booking(b2["id"], make_driver_headers(driver["id"])))
    get_success_data(api.check_out_booking(b2["id"], make_driver_headers(driver["id"])))

    host_after = get_success_data(api.get_host(host["id"], make_host_headers(host["id"])))
    assert host_after["lifetime_payout_cents"] == 1410, host_after["lifetime_payout_cents"]


def test_host_payout_single_earning_net_of_fee(api):
    """PRD §3.7: "The net earning is the gross minus that rounded fee, and the `EARNING`
    entry's `amount_cents` is the positive net earning."

    One booking gross 830 at fee 1500 bps: fee = round_half_up(124.5) = 125, net = 705.
    The host's lifetime after a single checkout is the single net earning, 705.

    Design: Difficulty/combinatorial_formula/host_payout_per_line_rounding_order_pinned
    """
    host = register_host(platform_fee_bps=1500)
    driver = register_driver()
    fund_driver(driver["id"], 5000)
    spot = create_spot(host["id"], base_hourly_cents=830, base_daily_cents=20000,
                       monthly_flat_cents=200000, zone_code="Z4b", overstay_grace_minutes=15)
    b1 = create_booking(spot["id"], driver["id"], "HOURLY",
                        "2026-04-08T10:00:00Z", "2026-04-08T11:00:00Z", spot["version"])
    set_clock("2026-04-08T10:00:00Z")
    get_success_data(api.check_in_booking(b1["id"], make_driver_headers(driver["id"])))
    get_success_data(api.check_out_booking(b1["id"], make_driver_headers(driver["id"])))
    host_after = get_success_data(api.get_host(host["id"], make_host_headers(host["id"])))
    assert host_after["lifetime_payout_cents"] == 705, host_after["lifetime_payout_cents"]


# ─── Corner: calculations ────────────────────────────────────────────────────

def test_monthly_flat_quote_ignores_surge(api):
    """PRD §3.3: "For a `MONTHLY` booking, the base is simply the spot's
    `monthly_flat_cents` for a single fixed 30-day block."

    A MONTHLY booking (exactly 30 days, 2026-05-01 .. 2026-05-31) with no matching event
    quotes the flat 120000.

    Design: Corner/calculations/monthly_flat_quote_ignores_surge_when_no_event
    """
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"monthly_flat_cents": 120000, "zone_code": "ZCA1",
                        "availability_end": "2026-07-01T00:00:00Z"},
        wallet_cents=200000)
    booking = create_booking(spot["id"], driver["id"], "MONTHLY",
                             "2026-05-01T00:00:00Z", "2026-05-31T00:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 120000, booking["quoted_amount_cents"]


def test_hourly_partial_hour_ceils_up(api):
    """PRD §3.3: "For an `HOURLY` booking, the duration in seconds is divided by 3600 and
    rounded up to the next whole hour, and that number of hours is multiplied by the spot's
    `base_hourly_cents`."

    A 2.5h HOURLY window at base 400 ceils to 3 hours -> 1200 (not 1000), weekday, no surge.

    Design: Corner/calculations/hourly_ceil_partial_hour_rounds_up
    """
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"base_hourly_cents": 400, "zone_code": "ZCA3"}, wallet_cents=5000)
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T12:30:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 1200, booking["quoted_amount_cents"]


def test_daily_weekend_uplift_applied(api):
    """PRD §3.3: "A weekend uplift then applies only to `HOURLY` and `DAILY` bookings whose
    `start_at` falls on a Saturday or Sunday in UTC: the weekend factor is 11000 basis
    points in that case and 10000 otherwise".

    A 1-day DAILY booking starting Saturday 2026-04-11 at base_daily 6000 applies 1.1x ->
    6600 (no surge event).

    Design: Corner/calculations/daily_weekend_uplift_applied
    """
    host, driver, spot = setup_host_driver_spot(
        spot_overrides={"base_daily_cents": 6000, "zone_code": "ZCA4"}, wallet_cents=20000)
    booking = create_booking(spot["id"], driver["id"], "DAILY",
                             "2026-04-11T08:00:00Z", "2026-04-12T08:00:00Z", spot["version"])
    assert booking["quoted_amount_cents"] == 6600, booking["quoted_amount_cents"]


def test_checkout_on_time_final_equals_quoted(api):
    """PRD §3.5: "if that overstay duration is zero or negative there is no overstay charge."
    PRD §3.5: "The final amount is the frozen `quoted_amount_cents` (the base portion is the
    quote, never re-priced) plus an overstay charge."

    Booking [10:00,12:00) quoted 800, checkout exactly at end+grace (12:15): overstay
    duration is zero, so final == quoted 800.

    Design: Corner/calculations/checkout_on_time_final_equals_quoted_no_overstay
    """
    host, driver, spot, booking = setup_checked_in_booking(
        start_at="2026-04-08T10:00:00Z", end_at="2026-04-08T12:00:00Z",
        spot_overrides={"base_hourly_cents": 400, "overstay_grace_minutes": 15})
    final = checkout_at(driver["id"], booking["id"], "2026-04-08T12:15:00Z")
    assert final["final_amount_cents"] == 800, final["final_amount_cents"]


def test_host_ledger_lists_earning_after_checkout(api):
    """PRD §3.7: "Whenever a booking is finalized in the host's favor — at checkout, or when
    a reservation is marked a no-show — the server posts a `PayoutLedgerEntry` of type
    `EARNING` for the spot's owning host."
    PRD §3.7: "The net earning is the gross minus that rounded fee, and the `EARNING`
    entry's `amount_cents` is the positive net earning."

    Booking quoted 800, checked in/out on time, host fee 1500 bps: fee = 120, net = 680.
    The ledger lists one EARNING of 680 and lifetime_payout_cents == 680.

    Design: Corner/endpoints/host_ledger_computed_read_lists_earning
    """
    host = register_host(platform_fee_bps=1500)
    driver = register_driver()
    fund_driver(driver["id"], 5000)
    spot = create_spot(host["id"], zone_code="ZEP2", overstay_grace_minutes=15)
    set_clock("2026-04-08T09:00:00Z")
    booking = create_booking(spot["id"], driver["id"], "HOURLY",
                             "2026-04-08T10:00:00Z", "2026-04-08T12:00:00Z", spot["version"])
    set_clock("2026-04-08T10:00:00Z")
    get_success_data(api.check_in_booking(booking["id"], make_driver_headers(driver["id"])))
    get_success_data(api.check_out_booking(booking["id"], make_driver_headers(driver["id"])))

    ledger, meta = validate_paginated(api.list_host_ledger(host["id"], make_host_headers(host["id"])))
    earnings = [e for e in ledger if e["entry_type"] == "EARNING"]
    assert len(earnings) == 1, ledger
    assert earnings[0]["amount_cents"] == 680, earnings[0]
    host_after = get_success_data(api.get_host(host["id"], make_host_headers(host["id"])))
    assert host_after["lifetime_payout_cents"] == 680
