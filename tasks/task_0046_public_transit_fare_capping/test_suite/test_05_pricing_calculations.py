"""Chronological pricing: discount stacking, per-ride rounding, daily/weekly caps,
transfer windows, the forward-looking quote divergence, and benefit application.

Covers Corner queue (B) calculations instances and Difficulty queue (A) rules
dual_variant_calc (the tap-charge instance), combinatorial_formula,
boundary_precision_check, and resource_temporal_overlap (the transfer-buffer instance).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    create_tap_payload, create_reduced_fare_card_payload, verify_payload,
    TEST_USERS, make_rider_headers,
    set_clock, register_rider, add_funding_source, load_balance, open_week,
    record_tap, settle, create_captured_tap, setup_funded_rider, create_verified_card,
    fund_allocation, get_fare_week, get_tap, get_allocation,
)


# ─── Difficulty rule dual_variant_calc ────────────────────────────────────
#   instance: tap_charge_chronological_vs_forward_diverge_on_out_of_order_quote

def test_quote_appends_out_of_order_tap_diverges_from_chronological(api):
    """PRD §3.9: "Instead of inserting the hypothetical tap into its chronological
    position, the quote treats it as appended to today's already-captured set
    regardless of its `tapped_at`."
    PRD §3.9: "a tap quoted with a `tapped_at` earlier than an already-captured tap
    is estimated as carrying cap-credit forward, whereas a real chronological settle
    would price that same earlier tap at full fare since it has no captured tap
    before it in time; the two figures diverge precisely when the quoted tap is out
    of eventual chronological order."

    Design: Difficulty/dual_variant_calc/tap_charge_chronological_vs_forward_diverge_on_out_of_order_quote
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 500, "weekly_cap_cents": 2500,
        "transfer_discount_pct": 0, "reduced_fare_pct": 0.5})
    # One CAPTURED tap at 08:00 charged 300.
    t1 = create_captured_tap(world, "2026-06-01T08:00:00Z")
    assert t1["charge_cents"] == 300
    # Quote a tap at 07:00 (earlier than the captured 08:00) — forward-looking appends:
    # daily list total 300 + this 300 = 600, capped at 500, minus charged 300 = 200.
    res = api.quote_tap(make_rider_headers(world["rider"]["id"]),
                        {"rider_id": world["rider"]["id"], "fare_week_id": world["week"]["id"],
                         "tapped_at": "2026-06-01T07:00:00Z"})
    quote = validate_success(res, 200)
    assert quote["estimated_charge_cents"] == 200


def test_chronological_settle_prices_earliest_tap_full_fare(api):
    """PRD §3.7: "The price is computed by chronologically replaying the rider's
    prior captured taps in the same fare day and the same week, so the result
    depends on the order in which taps were taken: a later-tapped ride absorbs cap
    credit while an earlier one pays the fuller fare."
    PRD §3.7 (step 3): "The day-charged-before amount is the sum of `charge_cents`
    over this rider's captured taps in the same fare day whose `tapped_at` is
    strictly before this tap's `tapped_at`".

    Design: Difficulty/dual_variant_calc/tap_charge_chronological_vs_forward_diverge_on_out_of_order_quote
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 500, "weekly_cap_cents": 2500,
        "transfer_discount_pct": 0, "reduced_fare_pct": 0.5})
    create_captured_tap(world, "2026-06-01T08:00:00Z")
    # A real tap at 07:00 has no captured tap strictly before it → full fare 300,
    # diverging from the 200 quote estimate.
    earlier = create_captured_tap(world, "2026-06-01T07:00:00Z")
    assert earlier["charge_cents"] == 300


# ─── Difficulty rule combinatorial_formula ────────────────────────────────
#   instance: discount_stacking_takes_max_then_min_caps_mode_a

def test_discount_stacking_takes_larger_discount(api):
    """PRD §3.7 (step 1): "If the rider's `income_tier` is `LOW_INCOME`, the
    effective discount becomes the larger of its current value and the rider's
    `low_income_discount_pct` — the system takes the larger of the two discounts and
    never sums them. The `list_fare_cents` is then the base fare multiplied by one
    minus the effective discount fraction, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/discount_stacking_takes_max_then_min_caps_mode_a
    """
    world = setup_funded_rider(rider_overrides={
        "income_tier": "LOW_INCOME", "low_income_discount_pct": 0.6},
        product_overrides={"base_fare_cents": 300, "daily_cap_cents": 500,
                           "weekly_cap_cents": 2500, "reduced_fare_pct": 0.5,
                           "transfer_discount_pct": 0})
    create_verified_card(world["rider"]["id"], program_code="SENIOR")
    # eff_discount = max(0.5, 0.6) = 0.6 → list_fare = round_half_up(300*0.4) = 120.
    # eff_daily_cap 200, eff_weekly_cap 1000 — neither binds; charge = 120.
    tap = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert tap["list_fare_cents"] == 120
    assert tap["charge_cents"] == 120


def test_low_income_discount_alone_applies_when_no_card(api):
    """PRD §3.7 (step 1): "If the rider's `income_tier` is `LOW_INCOME`, the
    effective discount becomes the larger of its current value and the rider's
    `low_income_discount_pct`". With no verified card, the effective discount is the
    rider's own 0.6, so the list fare is round_half_up(300*0.4) = 120.

    Design: Difficulty/combinatorial_formula/discount_stacking_takes_max_then_min_caps_mode_a
    """
    world = setup_funded_rider(rider_overrides={
        "income_tier": "LOW_INCOME", "low_income_discount_pct": 0.6},
        product_overrides={"base_fare_cents": 300, "daily_cap_cents": 500,
                           "weekly_cap_cents": 2500, "reduced_fare_pct": 0.5,
                           "transfer_discount_pct": 0})
    tap = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert tap["list_fare_cents"] == 120
    assert tap["charge_cents"] == 120


# ─── Difficulty rule combinatorial_formula ────────────────────────────────
#   instance: per_ride_rounding_before_sum_mode_b

def test_per_ride_rounding_before_sum(api):
    """PRD §2.5: "the product is rounded to the nearest whole cent using the
    round-half-up convention, and the rounding is applied at each such per-ride
    multiplication rather than deferred to the end."
    PRD §2.6: "Its `charged_total_cents` is a computed running sum of the
    out-of-pocket `charge_cents` over the `CAPTURED` taps belonging to that week".

    Design: Difficulty/combinatorial_formula/per_ride_rounding_before_sum_mode_b
    """
    world = setup_funded_rider(zone_code="ZONEY", product_overrides={
        "zone_code": "ZONEY", "base_fare_cents": 275, "daily_cap_cents": 5000,
        "weekly_cap_cents": 5000, "reduced_fare_pct": 0.5, "transfer_discount_pct": 0})
    create_verified_card(world["rider"]["id"], program_code="STUDENT")
    # Each ride: round_half_up(275*0.5) = round_half_up(137.5) = 138.
    ta = create_captured_tap(world, "2026-06-01T09:00:00Z")
    tb = create_captured_tap(world, "2026-06-01T11:00:00Z")
    tc = create_captured_tap(world, "2026-06-01T13:00:00Z")
    assert ta["charge_cents"] == 138
    assert tb["charge_cents"] == 138
    assert tc["charge_cents"] == 138
    week = get_fare_week(world["rider"]["id"], world["week"]["id"])
    assert week["charged_total_cents"] == 414, "per-ride round-then-sum (138*3), not 413"


def test_single_reduced_ride_rounds_half_up(api):
    """PRD §2.5: "the product is rounded to the nearest whole cent using the
    round-half-up convention". A single reduced ride at base 275, reduced_fare_pct
    0.5 rounds 137.5 up to 138.

    Design: Difficulty/combinatorial_formula/per_ride_rounding_before_sum_mode_b
    """
    world = setup_funded_rider(zone_code="ZONEY", product_overrides={
        "zone_code": "ZONEY", "base_fare_cents": 275, "daily_cap_cents": 5000,
        "weekly_cap_cents": 5000, "reduced_fare_pct": 0.5, "transfer_discount_pct": 0})
    create_verified_card(world["rider"]["id"], program_code="STUDENT")
    ta = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert ta["list_fare_cents"] == 138
    assert ta["charge_cents"] == 138


# ─── Difficulty rule boundary_precision_check ─────────────────────────────
#   instance: daily_cap_exact_hit_charges_zero_remaining_room

def test_daily_cap_exact_hit_third_tap_charges_zero(api):
    """PRD §3.7 (step 3): "The daily room is the effective daily cap minus the
    day-charged-before amount, floored at 0 ... The billable amount is the smallest
    of the post-transfer amount, the daily room, and the weekly room. The
    `cap_credit_cents` is the post-transfer amount minus the billable amount."

    Design: Difficulty/boundary_precision_check/daily_cap_exact_hit_charges_zero_remaining_room
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 500, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    ta = create_captured_tap(world, "2026-06-01T07:00:00Z")  # 300
    tb = create_captured_tap(world, "2026-06-01T09:00:00Z")  # clipped to 200 (cap 500)
    assert ta["charge_cents"] == 300
    assert tb["charge_cents"] == 200
    # Day already charged 500 == daily cap → daily_room is exactly 0.
    tc = create_captured_tap(world, "2026-06-01T11:00:00Z")
    assert tc["charge_cents"] == 0
    assert tc["cap_credit_cents"] == 300


def test_daily_cap_with_remaining_room_charges_partial(api):
    """PRD §3.7 (step 3): "The billable amount is the smallest of the post-transfer
    amount, the daily room, and the weekly room." With 300 already charged and a 500
    daily cap, the next ride's daily room is 200, so it is clipped to 200, not 0.

    Design: Difficulty/boundary_precision_check/daily_cap_exact_hit_charges_zero_remaining_room
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 500, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    create_captured_tap(world, "2026-06-01T07:00:00Z")  # 300
    tb = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert tb["charge_cents"] == 200
    assert tb["cap_credit_cents"] == 100


# ─── Difficulty rule boundary_precision_check ─────────────────────────────
#   instance: transfer_window_exact_minute_is_inclusive

def test_transfer_window_exact_minute_inclusive(api):
    """PRD §3.7 (step 2): "If such a prior tap exists and the gap from it to this tap
    is within the product's `transfer_window_minutes`, the `transfer_discount_cents`
    is the `list_fare_cents` multiplied by the product's `transfer_discount_pct`,
    rounded half up to a whole cent".

    Design: Difficulty/boundary_precision_check/transfer_window_exact_minute_is_inclusive
    """
    world = setup_funded_rider(zone_code="ZONEZ", product_overrides={
        "zone_code": "ZONEZ", "base_fare_cents": 300, "daily_cap_cents": 5000,
        "weekly_cap_cents": 5000, "transfer_window_minutes": 120,
        "transfer_discount_pct": 1.0})
    create_captured_tap(world, "2026-06-01T08:00:00Z")  # prior charged 300
    # Exactly 120 minutes later → inside the window (inclusive).
    t2 = create_captured_tap(world, "2026-06-01T10:00:00Z")
    assert t2["transfer_discount_cents"] == 300
    assert t2["charge_cents"] == 0


def test_transfer_window_one_minute_past_excluded(api):
    """PRD §3.7 (step 2): "If such a prior tap exists and the gap from it to this tap
    is within the product's `transfer_window_minutes` ... otherwise it is 0." One
    minute past the 120-minute window, the tap is not a transfer and pays full fare.

    Design: Difficulty/boundary_precision_check/transfer_window_exact_minute_is_inclusive
    """
    world = setup_funded_rider(zone_code="ZONEZ", product_overrides={
        "zone_code": "ZONEZ", "base_fare_cents": 300, "daily_cap_cents": 5000,
        "weekly_cap_cents": 5000, "transfer_window_minutes": 120,
        "transfer_discount_pct": 1.0})
    create_captured_tap(world, "2026-06-01T08:00:00Z")
    # 121 minutes later → outside the window.
    t2 = create_captured_tap(world, "2026-06-01T10:01:00Z")
    assert t2["transfer_discount_cents"] == 0
    assert t2["charge_cents"] == 300


# ─── Difficulty rule resource_temporal_overlap ────────────────────────────
#   instance: transfer_window_open_interval_overlap_on_funding_timeline

def test_transfer_buffer_inside_window_applies_discount(api):
    """PRD §3.7 (step 2): "The system finds the rider's most recent captured tap
    whose `tapped_at` is strictly before this tap's `tapped_at` ... If such a prior
    tap exists and the gap from it to this tap is within the product's
    `transfer_window_minutes`, the `transfer_discount_cents` is the `list_fare_cents`
    multiplied by the product's `transfer_discount_pct`, rounded half up to a whole
    cent".

    Design: Difficulty/resource_temporal_overlap/transfer_window_open_interval_overlap_on_funding_timeline
    """
    world = setup_funded_rider(zone_code="ZONEZ", product_overrides={
        "zone_code": "ZONEZ", "base_fare_cents": 300, "daily_cap_cents": 5000,
        "weekly_cap_cents": 5000, "transfer_window_minutes": 120,
        "transfer_discount_pct": 1.0})
    create_captured_tap(world, "2026-06-01T08:00:00Z")  # prior charged 300
    # 60 minutes later → inside the 120-min buffer measured from the prior tap.
    t2 = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert t2["transfer_discount_cents"] == 300


def test_no_prior_tap_means_no_transfer_discount(api):
    """PRD §3.7 (step 2): "The system finds the rider's most recent captured tap
    whose `tapped_at` is strictly before this tap's `tapped_at` ... otherwise it is
    0." The first tap of the timeline has no prior captured tap, so no transfer
    buffer applies and it pays full fare.

    Design: Difficulty/resource_temporal_overlap/transfer_window_open_interval_overlap_on_funding_timeline
    """
    world = setup_funded_rider(zone_code="ZONEZ", product_overrides={
        "zone_code": "ZONEZ", "base_fare_cents": 300, "daily_cap_cents": 5000,
        "weekly_cap_cents": 5000, "transfer_window_minutes": 120,
        "transfer_discount_pct": 1.0})
    first = create_captured_tap(world, "2026-06-01T08:00:00Z")
    assert first["transfer_discount_cents"] == 0
    assert first["charge_cents"] == 300


# ─── Corner: calculations section ─────────────────────────────────────────

def test_weekly_cap_clips_across_days(api):
    """PRD §3.7 (step 3): "The daily room is the effective daily cap minus the
    day-charged-before amount, floored at 0; the weekly room is the effective weekly
    cap minus the week-charged-before amount, floored at 0. The billable amount is
    the smallest of the post-transfer amount, the daily room, and the weekly room."

    Design: Corner/calculations/weekly_cap_clips_charge_across_days
    """
    world = setup_funded_rider(clock="2026-06-03T12:00:00Z", zone_code="ZONEW",
                               week_start="2026-06-01", product_overrides={
                                   "zone_code": "ZONEW", "base_fare_cents": 300,
                                   "daily_cap_cents": 500, "weekly_cap_cents": 1200,
                                   "transfer_discount_pct": 0})
    rid, wid, fid = world["rider"]["id"], world["week"]["id"], world["funding_source"]["id"]
    # Days 1-2 accrue to 1000 (each day: 300 + 200 cap-clipped).
    for day in ("2026-06-01", "2026-06-02"):
        for hour in ("09:00:00", "13:00:00"):
            settle(record_tap(rid, wid, fid, f"{day}T{hour}Z")["id"])
    # Day-3 tap: weekly_room == 1200 - 1000 == 200 binds before daily_room 500.
    d3 = settle(record_tap(rid, wid, fid, "2026-06-03T09:00:00Z")["id"])
    assert d3["charge_cents"] == 200
    week = get_fare_week(rid, wid)
    assert week["charged_total_cents"] == 1200


def test_unverified_card_excluded_pays_full_fare(api):
    """PRD §3.4: "Only a `VERIFIED`, unexpired card grants the reduced fare."
    PRD §3.7 (step 1): "If the rider holds a `VERIFIED` reduced-fare card whose
    `expires_on` is on or after the fare day, the effective discount becomes the
    product's `reduced_fare_pct`."

    Design: Corner/calculations/reduced_fare_card_halves_fare_input_set_filtering
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 5000, "weekly_cap_cents": 5000,
        "reduced_fare_pct": 0.5, "transfer_discount_pct": 0})
    # Apply for a card but DO NOT verify it — stays PENDING_VERIFICATION.
    validate_success(api.create_reduced_fare_card(
        create_reduced_fare_card_payload(world["rider"]["id"], program_code="STUDENT"),
        make_rider_headers(world["rider"]["id"])), 201)
    tap = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert tap["list_fare_cents"] == 300, "unverified card grants no discount"
    assert tap["charge_cents"] == 300


def test_benefit_selector_picks_active_allocation_with_headroom(api):
    """PRD §3.8: "Its candidate set is the `BenefitAllocation` rows that belong to
    the tap's rider, are in `ACTIVE` status, have a `period_month` equal to the fare
    day's `YYYY-MM`, and still have remaining headroom ... The selector returns the
    first candidate after this ordering."
    PRD §3.7 (step 4): "If an allocation is selected, `benefit_applied_cents` is the
    smaller of the billable amount and that allocation's remaining headroom".

    Design: Corner/calculations/benefit_selector_picks_most_headroom_then_oldest
    """
    world = setup_funded_rider(product_overrides={
        "base_fare_cents": 300, "daily_cap_cents": 5000, "weekly_cap_cents": 5000,
        "transfer_discount_pct": 0})
    alloc = fund_allocation(world["rider"]["id"], world["rider"]["version"],
                            employer_ref="EMPB", period_month="2026-06",
                            allocated_cents=1000)
    tap = create_captured_tap(world, "2026-06-01T09:00:00Z")
    assert tap["benefit_allocation_id"] == alloc["id"]
    assert tap["benefit_applied_cents"] == 300
    assert tap["charge_cents"] == 0
    refreshed = get_allocation(world["rider"]["id"], alloc["id"])
    assert refreshed["consumed_cents"] == 300
    assert refreshed["status"] == "ACTIVE"
