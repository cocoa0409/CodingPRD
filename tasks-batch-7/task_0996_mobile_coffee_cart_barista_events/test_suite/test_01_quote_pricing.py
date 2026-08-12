"""Quote pricing: dual pricing variants, travel variants, deposit clamp, and
the fixed subtotal -> zone-gate -> fee -> total evaluation order.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations, entities (quote-time computed fields).
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    assert_booking, assert_booking_addon,
    ApiErrorId,
)

ERR = ApiErrorId


# ─── dual_variant_calc / pricing_variant_flat_vs_percup_same_inputs ───────

def test_pricing_variants_diverge_on_same_inputs(api):
    """PRD §3.3: "The subtotal depends on the package's pricing variant, and the
    variant in force is recorded on the booking as `pricing_variant_used`."
    PRD §3.3: "With subtotal and fee in hand, the `quoted_total_cents` is their sum."

    Identical guest_count, distance, cart, and add-ons price differently under
    FLAT_PACKAGE (60000 + 10km x 200 = 62000, deposit 18600) versus
    PER_CUP_METERED (ceil(40 x 1.5) x 450 = 27000 + 2000 = 29000, deposit 8700).

    Design: Difficulty/dual_variant_calc/pricing_variant_flat_vs_percup_same_inputs
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    ctx_cup = dict(ctx)
    ctx_cup["package"] = fx.create_per_cup_package()

    flat_booking = fx.create_quote_booking(
        ctx, event_start="2026-05-10T10:00:00Z", event_end="2026-05-10T12:00:00Z")
    fx.offer_primary_assignment(ctx, flat_booking["id"])
    flat = fx.submit_quote(ctx, flat_booking["id"])

    cup_booking = fx.create_quote_booking(
        ctx_cup, event_start="2026-05-11T10:00:00Z", event_end="2026-05-11T13:00:00Z")
    fx.offer_primary_assignment(ctx_cup, cup_booking["id"])
    cup = fx.submit_quote(ctx_cup, cup_booking["id"])

    assert flat["pricing_variant_used"] == "FLAT_PACKAGE", flat
    assert cup["pricing_variant_used"] == "PER_CUP_METERED", cup
    assert flat["quoted_total_cents"] == 62000, flat
    assert cup["quoted_total_cents"] == 29000, cup
    assert flat["deposit_due_cents"] == 18600, flat
    assert cup["deposit_due_cents"] == 8700, cup
    assert flat["quoted_total_cents"] != cup["quoted_total_cents"]


def test_flat_package_quote_breakdown(api):
    """PRD §3.3: "Under the `FLAT_PACKAGE` variant — selected when the package's
    `pricing_model` is `FLAT` — the `quoted_subtotal_cents` is the package's
    `flat_price_cents` plus the sum of `applied_price_cents` over every add-on
    attached to the booking."
    PRD §3.3: "The raw figure is thirty percent of `quoted_total_cents`, rounded
    half-up to the nearest cent; the result is then clamped so that
    `deposit_due_cents` is never below one thousand cents and never above fifty
    thousand cents."

    FLAT package at 60000 with a 10 km metered leg (10 x 200): subtotal 60000,
    travel 2000, total 62000, deposit round_half_up(62000 x 0.30) = 18600.

    Design: Difficulty/dual_variant_calc/pricing_variant_flat_vs_percup_same_inputs
    """
    ctx = fx.setup_quote_with_assignment(package_kind="FLAT")
    submitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert_booking(submitted)
    assert submitted["status"] == "PENDING_DEPOSIT", submitted
    assert submitted["pricing_variant_used"] == "FLAT_PACKAGE", submitted
    assert submitted["travel_variant_used"] == "METERED", submitted
    assert submitted["quoted_subtotal_cents"] == 60000, submitted
    assert submitted["quoted_travel_fee_cents"] == 2000, submitted
    assert submitted["quoted_total_cents"] == 62000, submitted
    assert submitted["deposit_due_cents"] == 18600, submitted


def test_per_cup_quote_breakdown(api):
    """PRD §3.3: "That cup estimate is multiplied by the package's
    `per_cup_price_cents` to produce the metered amount; the subtotal is then the
    greater of the metered amount and the package's `per_cup_minimum_cents`, plus
    the sum of `applied_price_cents` over the attached add-ons."

    PER_CUP package (450/cup, floor 25000) with 40 guests: ceil(40 x 1.5) = 60
    cups, metered 27000 >= floor 25000, travel 10km x 200 = 2000, total 29000,
    deposit round_half_up(29000 x 0.30) = 8700.

    Design: Difficulty/dual_variant_calc/pricing_variant_flat_vs_percup_same_inputs
    """
    ctx = fx.setup_quote_with_assignment(package_kind="PER_CUP")
    submitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert submitted["pricing_variant_used"] == "PER_CUP_METERED", submitted
    assert submitted["quoted_subtotal_cents"] == 27000, submitted
    assert submitted["quoted_travel_fee_cents"] == 2000, submitted
    assert submitted["quoted_total_cents"] == 29000, submitted
    assert submitted["deposit_due_cents"] == 8700, submitted


# ─── combinatorial_formula / deposit_clamp_mode_a_multi_input_threshold ───

def _submit_flat_with_price(api, flat_price_cents, guest_count, max_guests):
    ctx = fx.setup_base_catalog(
        package_kind="FLAT",
        package_overrides={"flat_price_cents": flat_price_cents,
                           "max_guests": max_guests})
    booking = fx.create_quote_booking(ctx, guest_count=guest_count, distance_km=0)
    fx.offer_primary_assignment(ctx, booking["id"])
    return fx.submit_quote(ctx, booking["id"])


def test_deposit_clamped_up_to_minimum(api):
    """PRD §3.3: "The raw figure is thirty percent of `quoted_total_cents`, rounded
    half-up to the nearest cent; the result is then clamped so that
    `deposit_due_cents` is never below one thousand cents and never above fifty
    thousand cents."

    Total 2000 (distance 0, fee 0): raw 30% = 600, clamped up to the 1000 floor.

    Design: Difficulty/combinatorial_formula/deposit_clamp_mode_a_multi_input_threshold
    """
    submitted = _submit_flat_with_price(api, 2000, guest_count=10, max_guests=20)
    assert submitted["quoted_total_cents"] == 2000, submitted
    assert submitted["deposit_due_cents"] == 1000, submitted


def test_deposit_within_clamp_range_unmodified(api):
    """PRD §3.3: "The raw figure is thirty percent of `quoted_total_cents`, rounded
    half-up to the nearest cent; the result is then clamped so that
    `deposit_due_cents` is never below one thousand cents and never above fifty
    thousand cents."

    Total 60000: raw 30% = 18000 lands inside [1000, 50000], so no clamp applies.

    Design: Difficulty/combinatorial_formula/deposit_clamp_mode_a_multi_input_threshold
    """
    submitted = _submit_flat_with_price(api, 60000, guest_count=40, max_guests=80)
    assert submitted["quoted_total_cents"] == 60000, submitted
    assert submitted["deposit_due_cents"] == 18000, submitted


def test_deposit_clamped_down_to_maximum(api):
    """PRD §3.3: "The raw figure is thirty percent of `quoted_total_cents`, rounded
    half-up to the nearest cent; the result is then clamped so that
    `deposit_due_cents` is never below one thousand cents and never above fifty
    thousand cents."

    Total 200000: raw 30% = 60000, clamped down to the 50000 ceiling.

    Design: Difficulty/combinatorial_formula/deposit_clamp_mode_a_multi_input_threshold
    """
    submitted = _submit_flat_with_price(api, 200000, guest_count=400, max_guests=500)
    assert submitted["quoted_total_cents"] == 200000, submitted
    assert submitted["deposit_due_cents"] == 50000, submitted


# ─── combinatorial_formula / percup_ceil_then_multiply_mode_b_nested_rounding ───

def _submit_per_cup_with_guests(api, guest_count):
    ctx = fx.setup_base_catalog(package_kind="PER_CUP")
    booking = fx.create_quote_booking(ctx, guest_count=guest_count, distance_km=0)
    fx.offer_primary_assignment(ctx, booking["id"])
    return fx.submit_quote(ctx, booking["id"])


def test_cup_estimate_rounded_up_before_multiplying(api):
    """PRD §3.3: "the `guest_count` is multiplied by one and a half and the result
    is rounded up to the next whole cup. That cup estimate is multiplied by the
    package's `per_cup_price_cents` to produce the metered amount; the subtotal is
    then the greater of the metered amount and the package's
    `per_cup_minimum_cents`, plus the sum of `applied_price_cents` over the
    attached add-ons."

    guest_count=41 at 450/cup: ceil(41 x 1.5) = ceil(61.5) = 62 cups, so the
    subtotal is 62 x 450 = 27900 — not the 27675 that rounding after multiplying
    would produce.

    Design: Difficulty/combinatorial_formula/percup_ceil_then_multiply_mode_b_nested_rounding
    """
    submitted = _submit_per_cup_with_guests(api, 41)
    assert submitted["quoted_subtotal_cents"] == 27900, submitted
    assert submitted["quoted_subtotal_cents"] != 27675, submitted


def test_per_cup_total_equals_subtotal_when_distance_zero(api):
    """PRD §3.3: "With subtotal and fee in hand, the `quoted_total_cents` is their
    sum."
    PRD §3.3: "The subtotal depends on the package's pricing variant, and the
    variant in force is recorded on the booking as `pricing_variant_used`."

    distance_km=0 metered leg fees 0, so total == subtotal == 27900 and the
    pinned variant is PER_CUP_METERED.

    Design: Difficulty/combinatorial_formula/percup_ceil_then_multiply_mode_b_nested_rounding
    """
    submitted = _submit_per_cup_with_guests(api, 41)
    assert submitted["pricing_variant_used"] == "PER_CUP_METERED", submitted
    assert submitted["quoted_travel_fee_cents"] == 0, submitted
    assert submitted["quoted_total_cents"] == 27900, submitted


# ─── combinatorial_formula / travel_subtotal_eval_order_mode_c_circular_resolution ───

def _setup_low_subtotal_booking():
    """FLAT package priced 8000 against a zone whose min_booking_subtotal_cents
    is 10000; distance 40 km (banded leg)."""
    ctx = fx.setup_base_catalog(
        package_kind="FLAT",
        package_overrides={"flat_price_cents": 8000, "max_guests": 20},
        zone_overrides={"max_distance_km": 60, "banded_fee_cents": 15000,
                        "per_km_rate_cents": 300,
                        "min_booking_subtotal_cents": 10000})
    booking = fx.create_quote_booking(ctx, guest_count=10, distance_km=40)
    fx.offer_primary_assignment(ctx, booking["id"])
    return ctx, booking


def test_zone_tier_gate_rejects_subtotal_below_minimum(api):
    """PRD §3.3: "Before any fee arithmetic runs, the zone's tier gate is evaluated:
    if the freshly computed `quoted_subtotal_cents` falls short of the zone's
    `min_booking_subtotal_cents`, the quote is rejected with
    `ERR_SUBTOTAL_BELOW_ZONE_MINIMUM` (HTTP 422)."

    Subtotal 8000 < zone minimum 10000; the fee (which would lift the booking over
    10000) never counts toward the gate.

    Design: Difficulty/combinatorial_formula/travel_subtotal_eval_order_mode_c_circular_resolution
    """
    ctx, booking = _setup_low_subtotal_booking()
    res = fx.submit_quote_raw(
        ctx, booking["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    validate_error(res, ERR.ERR_SUBTOTAL_BELOW_ZONE_MINIMUM, expected_status=422)


def test_rejected_submission_leaves_booking_unpriced_in_quote(api):
    """PRD §3.2: "The new booking lands in `QUOTE` status, and its financial fields —
    `quoted_subtotal_cents`, `quoted_travel_fee_cents`, `quoted_total_cents`, and
    `deposit_due_cents` — stay at zero until the quote is submitted."
    PRD §3.3: "Quote math runs in a fixed order: subtotal first, then the zone's
    tier gate, then the travel fee, then the total."

    A submission rejected at the zone gate is never submitted: the booking stays
    in QUOTE with every financial field still at zero.

    Design: Difficulty/combinatorial_formula/travel_subtotal_eval_order_mode_c_circular_resolution
    """
    ctx, booking = _setup_low_subtotal_booking()
    res = fx.submit_quote_raw(
        ctx, booking["id"],
        fx.current_cart_version(ctx["cart"]["id"]),
        fx.current_barista_version(ctx["barista"]["id"]))
    validate_error(res, ERR.ERR_SUBTOTAL_BELOW_ZONE_MINIMUM, expected_status=422)

    after = validate_success(api.get_booking(booking["id"], fx.OPS), 200)
    assert after["status"] == "QUOTE", after
    assert after["quoted_subtotal_cents"] == 0, after
    assert after["quoted_travel_fee_cents"] == 0, after
    assert after["quoted_total_cents"] == 0, after
    assert after["deposit_due_cents"] == 0, after


# ─── Corner/calculations: travel variant selection ────────────────────────

def test_metered_travel_variant_applied_under_25km(api):
    """PRD §3.3: "when `distance_km` is at most twenty-five kilometers the `METERED`
    variant applies and the `quoted_travel_fee_cents` is the `distance_km`
    multiplied by the zone's `per_km_rate_cents`; otherwise the `BANDED` variant
    applies and the fee is the zone's flat `banded_fee_cents`."
    PRD §3.3: "The variant in force is recorded as `travel_variant_used`."

    distance_km=20 (<= 25) on a zone with per_km_rate_cents=200: fee 20 x 200 =
    4000, variant METERED.

    Design: Corner/calculations/metered_travel_variant_applied_when_distance_under_threshold
    """
    ctx = fx.setup_quote_with_assignment(
        package_kind="FLAT", booking_overrides={"distance_km": 20})
    submitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert submitted["travel_variant_used"] == "METERED", submitted
    assert submitted["quoted_travel_fee_cents"] == 4000, submitted
    assert submitted["quoted_total_cents"] == 64000, submitted


def test_banded_travel_variant_applied_over_25km(api):
    """PRD §3.3: "when `distance_km` is at most twenty-five kilometers the `METERED`
    variant applies and the `quoted_travel_fee_cents` is the `distance_km`
    multiplied by the zone's `per_km_rate_cents`; otherwise the `BANDED` variant
    applies and the fee is the zone's flat `banded_fee_cents`."
    PRD §3.3: "The variant in force is recorded as `travel_variant_used`."

    distance_km=30 (> 25): fee is the zone's flat banded_fee_cents = 5000,
    independent of the exact distance.

    Design: Corner/calculations/banded_travel_variant_applied_when_distance_over_threshold
    """
    ctx = fx.setup_quote_with_assignment(
        package_kind="FLAT", booking_overrides={"distance_km": 30})
    submitted = fx.submit_quote(ctx, ctx["booking"]["id"])
    assert submitted["travel_variant_used"] == "BANDED", submitted
    assert submitted["quoted_travel_fee_cents"] == 5000, submitted
    assert submitted["quoted_total_cents"] == 65000, submitted


# ─── Corner/entities: quote-time computed fields ──────────────────────────

def test_booking_financial_fields_zero_until_submitted(api):
    """PRD §3.2: "The new booking lands in `QUOTE` status, and its financial fields —
    `quoted_subtotal_cents`, `quoted_travel_fee_cents`, `quoted_total_cents`, and
    `deposit_due_cents` — stay at zero until the quote is submitted."

    A freshly created booking reports QUOTE with all four financial fields at 0.

    Design: Corner/entities/booking_computed_fields_initialized_zero
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    booking = fx.create_quote_booking(ctx)
    assert_booking(booking)
    assert booking["status"] == "QUOTE", booking
    assert booking["quoted_subtotal_cents"] == 0, booking
    assert booking["quoted_travel_fee_cents"] == 0, booking
    assert booking["quoted_total_cents"] == 0, booking
    assert booking["deposit_due_cents"] == 0, booking


def test_booking_addon_snapshots_price_at_attach_time(api):
    """PRD §3.2: "Attaching creates a BookingAddOn whose `booking_id` ties it to the
    booking and whose `applied_price_cents` snapshots the AddOn's `price_cents` at
    attach time — the snapshot is immutable afterwards, so later catalog price
    changes never retroactively alter a quote."

    Attaching an 8000-cent add-on to a QUOTE booking records
    applied_price_cents == 8000.

    Design: Corner/entities/booking_addon_applied_price_snapshot
    """
    ctx = fx.setup_base_catalog(package_kind="FLAT")
    addon = fx.create_addon(price_cents=8000)
    booking = fx.create_quote_booking(ctx)
    attach_res = api.attach_addon(booking["id"], {"addon_id": addon["id"]},
                                  ctx["client_headers"])
    booking_addon = validate_success(attach_res, 201)
    assert_booking_addon(booking_addon)
    assert booking_addon["applied_price_cents"] == 8000, booking_addon
    assert booking_addon["booking_id"] == booking["id"], booking_addon
    assert booking_addon["addon_id"] == addon["id"], booking_addon
