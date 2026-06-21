"""Nightly pricing, booking-total rounding order, and pricing quotes.

Covers difficulty rule combinatorial_formula and corner-section calculations
instances that exercise the nightly_pricing and booking_total rules.
"""
from test_helpers import (
    api_client,
    validate_success,
    make_host_headers,
    make_guest_headers,
    create_host, create_guest, create_listed_listing, add_rate_plan,
    get_calendar_version, create_booking, create_draft_listing,
)


# ==========================================================================
# Difficulty: combinatorial_formula
# ==========================================================================
def test_quote_nightly_multiplier_selection_weekend_branching(api):
    """PRD §3.4: "the seasonal multiplier for the night is the plan's
    `seasonal_multiplier_bps`, and the weekend multiplier is the plan's
    `weekend_multiplier_bps` when the date falls on a Friday or Saturday and
    10000 basis points otherwise. The price for that single night is the
    `base_nightly_rate_cents` multiplied by the seasonal multiplier divided by
    10000 and then by the weekend multiplier divided by 10000, with that
    per-night amount rounded to whole cents using round-half-up before it is
    added in."

    Design: Difficulty/combinatorial_formula/nightly_pricing_multiplier_selection_mode_a
    """
    host = create_host()
    _, listing = create_draft_listing(
        host=host,
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "pet_fee_cents": 3000, "tax_rate_bps": 1000},
    )
    add_rate_plan(host, listing, label="PEAK", window_start="2026-07-01",
                  window_end="2026-07-31", seasonal_multiplier_bps=15000,
                  weekend_multiplier_bps=12000)
    resp = api.quote_listing(
        listing["id"], headers=make_host_headers(host["id"]),
        params={"check_in": "2026-07-10", "check_out": "2026-07-13", "pets_count": 1})
    data = validate_success(resp)
    # 2026-07-10 Fri: 20000*1.5*1.2=36000; 07-11 Sat: 36000; 07-12 Sun: 20000*1.5=30000
    assert data["nightly_subtotal_cents"] == 102000, \
        f"Expected 102000, got {data['nightly_subtotal_cents']}"


def test_quote_nightly_pricing_three_input_interaction(api):
    """PRD §3.4: "The price for that single night is the `base_nightly_rate_cents`
    multiplied by the seasonal multiplier divided by 10000 and then by the
    weekend multiplier divided by 10000, with that per-night amount rounded to
    whole cents using round-half-up before it is added in. Each night is rounded
    individually and then the rounded per-night prices are summed; the resulting
    sum is the booking's `nightly_subtotal_cents`."

    Second test of the multiplier-selection rule on a different (non-weekend)
    single-night slice to pin the seasonal-only branch.

    Design: Difficulty/combinatorial_formula/nightly_pricing_multiplier_selection_mode_a
    """
    host = create_host()
    _, listing = create_draft_listing(
        host=host,
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "tax_rate_bps": 0},
    )
    add_rate_plan(host, listing, label="PEAK", window_start="2026-07-01",
                  window_end="2026-07-31", seasonal_multiplier_bps=15000,
                  weekend_multiplier_bps=12000)
    # 2026-07-12(Sun)..07-13: one Sunday night, seasonal only = 20000*1.5 = 30000.
    resp = api.quote_listing(
        listing["id"], headers=make_host_headers(host["id"]),
        params={"check_in": "2026-07-12", "check_out": "2026-07-13"})
    data = validate_success(resp)
    assert data["nightly_subtotal_cents"] == 30000, \
        f"Expected 30000 for one weekday-rate night, got {data['nightly_subtotal_cents']}"


def test_booking_total_rounding_order_tax_once(api):
    """PRD §3.4: "The taxable base is `nightly_subtotal_cents` plus `fees_cents`.
    The `tax_cents` is that taxable base multiplied by the listing's `tax_rate_bps`
    divided by 10000, rounded once with round-half-up after the base has been
    summed (the tax is not rounded per component). The guest grand total,
    `total_cents`, is the exact integer sum of `nightly_subtotal_cents`,
    `fees_cents`, and `tax_cents`."

    Design: Difficulty/combinatorial_formula/booking_total_rounding_order_mode_b
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True, prior_cancellations=0, chargeback_flag=False)
    _, listing = create_listed_listing(
        host=host,
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "pet_fee_cents": 3000, "tax_rate_bps": 1000},
        rate_plan_overrides={"label": "PEAK", "window_start": "2026-07-01",
                             "window_end": "2026-07-31", "seasonal_multiplier_bps": 15000,
                             "weekend_multiplier_bps": 12000},
    )
    booking = create_booking(host, listing, guest, check_in="2026-07-10",
                             check_out="2026-07-13", pets_count=1)
    assert booking["nightly_subtotal_cents"] == 102000
    assert booking["fees_cents"] == 8000, "cleaning 5000 + pet 3000"
    assert booking["tax_cents"] == 11000, "110000 * 1000/10000, rounded once"
    assert booking["total_cents"] == 121000


def test_booking_total_fees_component_pinned(api):
    """PRD §3.4: "The `fees_cents` is the listing's `cleaning_fee_cents` plus,
    only when `pets_count` is greater than zero, the listing's `pet_fee_cents`;
    with no pets only the cleaning fee applies."

    Second test of booking_total — pins fees_cents and total_cents on the
    rounding-order path with pets present.

    Design: Difficulty/combinatorial_formula/booking_total_rounding_order_mode_b
    """
    host = create_host()
    guest = create_guest(govt_id_verified=True, prior_cancellations=0, chargeback_flag=False)
    _, listing = create_listed_listing(
        host=host,
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "pet_fee_cents": 3000, "tax_rate_bps": 1000},
        rate_plan_overrides={"label": "PEAK", "window_start": "2026-07-01",
                             "window_end": "2026-07-31", "seasonal_multiplier_bps": 15000,
                             "weekend_multiplier_bps": 12000},
    )
    booking = create_booking(host, listing, guest, check_in="2026-07-10",
                             check_out="2026-07-13", pets_count=1)
    # taxable_base = 102000 + 8000 = 110000; tax = 11000; total = 121000.
    assert booking["fees_cents"] == 8000
    assert booking["total_cents"] == booking["nightly_subtotal_cents"] + booking["fees_cents"] + booking["tax_cents"]
    assert booking["total_cents"] == 121000


# ==========================================================================
# Corner: calculations
# ==========================================================================
def test_quote_no_rate_plan_prices_at_base(api):
    """PRD §3.4: "if no plan contains the date, that night uses a seasonal
    multiplier of 10000 basis points and a weekend multiplier of 10000 basis
    points (each a factor of 1.0)."

    Design: Corner/calculations/nightly_pricing_no_rate_plan_defaults_to_base
    """
    host = create_host()
    _, listing = create_draft_listing(
        host=host,
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "tax_rate_bps": 0},
    )
    # No rate plan; 2026-12-01..12-04 (Tue, Wed, Thu — no Fri/Sat).
    resp = api.quote_listing(
        listing["id"], headers=make_host_headers(host["id"]),
        params={"check_in": "2026-12-01", "check_out": "2026-12-04"})
    data = validate_success(resp)
    assert data["nightly_subtotal_cents"] == 60000, \
        f"Expected 3*20000=60000 with no multiplier, got {data['nightly_subtotal_cents']}"


def test_quote_pet_fee_omitted_when_zero_pets(api):
    """PRD §3.4: "The `fees_cents` is the listing's `cleaning_fee_cents` plus,
    only when `pets_count` is greater than zero, the listing's `pet_fee_cents`;
    with no pets only the cleaning fee applies."

    Design: Corner/calculations/pet_fee_omitted_when_zero_pets
    """
    host = create_host()
    _, listing = create_draft_listing(
        host=host,
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "pet_fee_cents": 3000, "tax_rate_bps": 0},
    )
    resp = api.quote_listing(
        listing["id"], headers=make_host_headers(host["id"]),
        params={"check_in": "2026-12-01", "check_out": "2026-12-04"})
    data = validate_success(resp)
    assert data["fees_cents"] == 5000, \
        f"Expected cleaning-only 5000 when pets omitted, got {data['fees_cents']}"
