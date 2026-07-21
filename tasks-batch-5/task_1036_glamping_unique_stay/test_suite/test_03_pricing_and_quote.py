"""The tiered pricing engine: multi-window totals, rounding order, and the
quote-vs-final dual-variant divergence.

Covers difficulty queue A (combinatorial formula, dual-variant calculation).
"""
from test_helpers import (
    validate_success, make_host_headers, make_guest_headers,
    attach_add_on_payload,
)
import test_helpers.fixtures as fx


# ---------------------- difficulty: combinatorial_formula (2a) two windows + addons
def _setup_two_window_listing_with_addons():
    env = fx.setup_listed_listing(
        site_type="CABIN", max_guests=6, min_nights=1, base_nightly_rate_cents=20000,
        cleaning_fee_cents=4000, cancellation_policy="FLEXIBLE", permit_type="CAMPING",
        rate_windows=[
            {"start_date": "2026-07-01T00:00:00Z", "end_date": "2026-07-08T00:00:00Z",
             "nightly_rate_cents": 20000},
            {"start_date": "2026-07-08T00:00:00Z", "end_date": "2026-08-01T00:00:00Z",
             "nightly_rate_cents": 30000},
        ],
    )
    firewood = fx.create_add_on(env["host"]["id"], env["listing"]["id"],
                                name="Firewood", category="AMENITY",
                                pricing_unit="PER_NIGHT", price_cents=1500)
    breakfast = fx.create_add_on(env["host"]["id"], env["listing"]["id"],
                                 name="Breakfast", category="AMENITY",
                                 pricing_unit="PER_GUEST", price_cents=1000)
    env["firewood"] = firewood
    env["breakfast"] = breakfast
    return env


def test_multi_window_stay_computes_nights_across_two_rate_windows(api):
    """PRD §3.5: "The occupancy interval is the half-open range from `check_in`
    up to but not including `check_out`, and `nights` is the whole number of days
    between them."

    Design: Difficulty/combinatorial_formula/multi_input_tiered_total_two_windows_and_addons
    """
    env = _setup_two_window_listing_with_addons()
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-05T00:00:00Z", "2026-07-15T00:00:00Z",
                                 guest_count=4)
    assert booking["nights"] == 10


def test_multi_window_tiered_total_with_per_night_and_per_guest_addons(api):
    """PRD §3.5: "For each night in the stay, the nightly rate is the
    `nightly_rate_cents` of the seasonal window covering that night's date; the
    nightly subtotal is the sum of those per-night rates."
    PRD §3.5: "a `PER_NIGHT` line contributes `price_cents` multiplied by
    `nights`; a `PER_GUEST` line contributes `price_cents` multiplied by
    `guest_count`."
    PRD §3.5: "A guest service fee of 12 percent is applied to that subtotal —
    computed on the summed subtotal and then rounded once, half-up — and
    `quoted_total_cents` is the subtotal plus that guest fee."

    Design: Difficulty/combinatorial_formula/multi_input_tiered_total_two_windows_and_addons
    """
    env = _setup_two_window_listing_with_addons()
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-05T00:00:00Z", "2026-07-15T00:00:00Z",
                                 guest_count=4)
    gh = make_guest_headers(env["guest"]["id"])
    api.attach_add_on(booking["id"], attach_add_on_payload(env["firewood"]["id"]), gh)
    resp = api.attach_add_on(booking["id"],
                             attach_add_on_payload(env["breakfast"]["id"]), gh)
    data = validate_success(resp, 200)
    assert data["quoted_total_cents"] == 297920


# --------------------- difficulty: combinatorial_formula (2b) rounding order
def test_rounding_order_stay_length_nights(api):
    """PRD §3.5: "The occupancy interval is the half-open range from `check_in`
    up to but not including `check_out`, and `nights` is the whole number of days
    between them."

    Design: Difficulty/combinatorial_formula/rounding_order_discount_sum_then_round
    """
    env = fx.setup_listed_listing(site_type="DOME", max_guests=2, min_nights=1,
                                  base_nightly_rate_cents=33333, cleaning_fee_cents=0,
                                  cancellation_policy="STRICT", permit_type="SPECIAL_USE",
                                  rate_cents=33333, rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-17T00:00:00Z",
                                 guest_count=1)
    assert booking["nights"] == 7


def test_rounding_order_discount_applied_to_summed_subtotal_then_rounded_once(api):
    """PRD §3.5: "The discounted nightly amount is the nightly subtotal multiplied
    by one minus the chosen discount fraction, with that product rounded once,
    half-up, to a whole cent — the discount is applied to the summed subtotal,
    never to each night individually."
    PRD §3.5: "otherwise a weekly discount of 10 percent applies when the stay is
    7 nights or longer, otherwise no discount applies."

    7 nights @33333 = 233331; round(233331 * 0.9) = 209998 (not 210000 that
    per-night rounding would give); with the 12% guest fee the quote is 235198.

    Design: Difficulty/combinatorial_formula/rounding_order_discount_sum_then_round
    """
    env = fx.setup_listed_listing(site_type="DOME", max_guests=2, min_nights=1,
                                  base_nightly_rate_cents=33333, cleaning_fee_cents=0,
                                  cancellation_policy="STRICT", permit_type="SPECIAL_USE",
                                  rate_cents=33333, rate_end="2026-08-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-17T00:00:00Z",
                                 guest_count=1)
    assert booking["quoted_total_cents"] == 235198


# ------------------- difficulty: dual_variant_calc (1a) quote vs final on reprice
def test_quoted_total_locked_at_request_time(api):
    """PRD §3.5: "A guest service fee of 12 percent is applied to that subtotal —
    computed on the summed subtotal and then rounded once, half-up — and
    `quoted_total_cents` is the subtotal plus that guest fee."
    PRD §3.6: "until acceptance, `final_total_cents` is null."

    3 nights @25000 (75000) + cleaning 5000 = 80000 subtotal; guest fee
    round(80000*0.12)=9600; quoted_total_cents = 89600.

    Design: Difficulty/dual_variant_calc/booking_quote_vs_final_diverge_on_reprice
    """
    env = fx.setup_listed_listing(site_type="YURT", max_guests=4, min_nights=2,
                                  base_nightly_rate_cents=20000, cleaning_fee_cents=5000,
                                  cancellation_policy="MODERATE",
                                  rate_cents=25000, rate_end="2026-09-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    assert booking["quoted_total_cents"] == 89600
    assert booking["final_total_cents"] is None


def test_final_total_relocked_at_accept_after_reprice_diverges_from_quote(api):
    """PRD §3.6: "On acceptance the guest total is re-computed and locked as
    `final_total_cents`, using exactly the same formula as the request-time quote
    but evaluated against the seasonal rates and add-on prices in effect at accept
    time."
    PRD §3.6: "Consequently `final_total_cents` diverges from `quoted_total_cents`
    precisely when the host changed a covering window's `nightly_rate_cents` or an
    add-on's `price_cents` between request and accept; until acceptance,
    `final_total_cents` is null."

    Reprice 25000 -> 30000 before accept: final = 90000 stay + 5000 cleaning =
    95000 subtotal; guest fee round(95000*0.12)=11400; final_total_cents = 106400.

    Design: Difficulty/dual_variant_calc/booking_quote_vs_final_diverge_on_reprice
    """
    env = fx.setup_listed_listing(site_type="YURT", max_guests=4, min_nights=2,
                                  base_nightly_rate_cents=20000, cleaning_fee_cents=5000,
                                  cancellation_policy="MODERATE",
                                  rate_cents=25000, rate_end="2026-09-01T00:00:00Z")
    booking = fx.request_booking(env["listing"]["id"], env["guest"]["id"],
                                 "2026-07-10T00:00:00Z", "2026-07-13T00:00:00Z")
    assert booking["quoted_total_cents"] == 89600
    fx.reprice_rate(env["host"]["id"], env["rates"][0]["id"], nightly_rate_cents=30000)
    resp = api.accept_booking(booking["id"], make_host_headers(env["host"]["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CONFIRMED"
    assert data["final_total_cents"] == 106400
