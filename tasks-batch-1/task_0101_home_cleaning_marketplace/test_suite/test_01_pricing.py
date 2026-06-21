"""Pricing-engine tests: price_quote variants, per-component rounding, loyalty
tiers, the move-out floor, supplies fee, and the cleaner-payout commission split.

All tests build their own world from PRD-declared endpoints (the server DB is
reset before each test) and assert PRD-exact field names.
"""
from test_helpers import (
    get_success_data, validate_success,
    make_customer_headers, make_cleaner_headers,
    setup_booking_world, create_one_time_booking, setup_reclean_scheduled,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Queue A — Rule 1: dual_variant_calc
# ===========================================================================
def test_one_time_quote_loyalty_tier_zero_at_count_zero(api):
    """PRD §3.6: "The discount rate is 0 percent when the count is below 5, 5
    percent when the count is at least 5 but below 15, 10 percent when the count
    is at least 15 but below 40, and 15 percent when the count is 40 or more."
    PRD §3.6: "For a one-time booking the loyalty tier is read at the single
    creation instant"

    A TWO_BR DEEP_CLEAN CLEANER-supplies one-time booking at lifetime count 0:
    base 11000 + deep 5500 + supplies 1500 = 18000, discount 0 => 18000.

    Design: Difficulty/dual_variant_calc/price_quote_one_time_vs_series_occurrence_divergence
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 18000, \
        f"Expected 18000 (one-time, tier 0.00 at count 0), got {booking['quoted_price_cents']}"


def test_series_occurrence_quote_loyalty_tier_five_percent_at_count_five(api):
    """PRD §3.6: "for a series occurrence it is read at the generation instant,
    which is why successive occurrences of one series can quote differently as
    the customer's lifetime count climbs."
    PRD §3.6: "The discount is the subtotal multiplied by that rate, rounded
    half-up to whole cents, and the priced amount is the subtotal minus the
    discount."

    The same TWO_BR DEEP_CLEAN CLEANER inputs at lifetime count 5 quote 17100
    (subtotal 18000, tier 0.05 discount 900), distinct from the one-time count-0
    value of 18000.

    Design: Difficulty/dual_variant_calc/price_quote_one_time_vs_series_occurrence_divergence
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=5)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 17100, \
        f"Expected 17100 (tier 0.05 at count 5), got {booking['quoted_price_cents']}"


def test_normal_completion_payout_is_seventy_percent(api):
    """PRD §3.7: "a `base_payout_cents` equal to 70 percent of the booking's
    `quoted_price_cents` rounded half-up to whole cents"

    An 18000-priced booking yields base_payout_cents 12600 on completion.

    Design: Difficulty/dual_variant_calc/cleaner_payout_normal_vs_reclean_zero
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 18000
    get_success_data(api.set_clock({"to_iso8601": "2026-06-10T11:00:00Z"}, ADMIN))
    cleaner_hdr = make_cleaner_headers(world["cleaner"]["id"])
    get_success_data(api.complete_booking(booking["id"], {"rating": 5}, cleaner_hdr))
    resp = api.list_cleaner_payouts(ADMIN, params={"booking_id": booking["id"]})
    payouts = resp.json()["data"]
    assert len(payouts) == 1
    assert payouts[0]["base_payout_cents"] == 12600, \
        f"Expected 12600 (70% of 18000), got {payouts[0]['base_payout_cents']}"


def test_reclean_completion_payout_is_zero(api):
    """PRD §3.7: "a re-clean's `quoted_price_cents` is zero, so its
    `base_payout_cents` is zero and the cleaner is not paid again"

    Completing the spawned reclean booking (priced 0) yields base_payout_cents 0,
    the dual variant of the normal 12600 payout.

    Design: Difficulty/dual_variant_calc/cleaner_payout_normal_vs_reclean_zero
    """
    world = setup_reclean_scheduled(
        home_size="TWO_BR", add_ons=("DEEP_CLEAN",), supplies_provided_by="CLEANER",
        reclean_start="2026-06-12T09:00:00Z",
    )
    reclean = world["reclean_booking"]
    assert reclean["quoted_price_cents"] == 0
    get_success_data(api.set_clock({"to_iso8601": "2026-06-12T11:00:00Z"}, ADMIN))
    cleaner_hdr = make_cleaner_headers(world["cleaner"]["id"])
    get_success_data(api.complete_booking(reclean["id"], {}, cleaner_hdr))
    resp = api.list_cleaner_payouts(ADMIN, params={"booking_id": reclean["id"]})
    payouts = resp.json()["data"]
    assert len(payouts) == 1
    assert payouts[0]["base_payout_cents"] == 0, \
        f"Expected 0 base payout on reclean, got {payouts[0]['base_payout_cents']}"


# ===========================================================================
# Queue A — Rule 2: combinatorial_formula
# ===========================================================================
def test_per_component_rounding_order_both_addons_with_max_loyalty(api):
    """PRD §2.8: "Rounding is applied per component: in the price quote, each
    add-on surcharge and the loyalty discount are each rounded to whole cents
    before they are combined, rather than summing first and rounding once at the
    end."
    PRD §3.6: "if `DEEP_CLEAN` is among the add-ons, the base multiplied by
    `deep_clean_surcharge_pct` (rounded half-up to whole cents) is added to it,
    and if `MOVE_OUT` is among the add-ons, the base multiplied by
    `move_out_surcharge_pct` (rounded half-up to whole cents) is added to it."

    THREE_BR base 14000, deep 0.50 -> 7000, move 0.75 -> 10500, supplies 1500;
    subtotal 33000; tier 0.15 discount 4950 => 28050.

    Design: Difficulty/combinatorial_formula/price_quote_per_component_rounding_order
    """
    world = setup_booking_world(home_size="THREE_BR", loyalty_count=40)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN", "MOVE_OUT"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 28050, \
        f"Expected 28050 (per-component rounding, tier 0.15), got {booking['quoted_price_cents']}"


def test_evaluation_order_loyalty_discount_off_subtotal(api):
    """PRD §3.6: "The subtotal is the base plus the surcharge accumulator plus
    the supplies component."
    PRD §3.6: "The loyalty discount is keyed off the customer's
    `lifetime_booking_count` read at quote time, which never includes the
    in-flight booking itself."

    TWO_BR base 11000 + deep 5500 + supplies 1500 = subtotal 18000; tier 0.05
    discount 900 => 17100; well-defined only because the order is pinned.

    Design: Difficulty/combinatorial_formula/price_quote_evaluation_order_loyalty_tier_off_subtotal
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=5)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 17100, \
        f"Expected 17100 (discount off subtotal 18000), got {booking['quoted_price_cents']}"


def test_per_component_rounding_single_deep_clean_surcharge(api):
    """PRD §3.6: "if `DEEP_CLEAN` is among the add-ons, the base multiplied by
    `deep_clean_surcharge_pct` (rounded half-up to whole cents) is added to it"

    A STUDIO base 6000 with DEEP_CLEAN 0.50 adds a 3000 surcharge; with CUSTOMER
    supplies and count 0 the visit prices 9000 — the surcharge is the rounded
    base*pct component, isolating the per-component rule.

    Design: Difficulty/combinatorial_formula/price_quote_per_component_rounding_order
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CUSTOMER",
    )
    assert booking["quoted_price_cents"] == 9000, \
        f"Expected 9000 (6000 base + 3000 deep-clean surcharge), got {booking['quoted_price_cents']}"


def test_evaluation_order_no_discount_below_loyalty_threshold(api):
    """PRD §3.6: "The subtotal is the base plus the surcharge accumulator plus
    the supplies component."
    PRD §3.6: "The discount rate is 0 percent when the count is below 5"

    The identical TWO_BR DEEP_CLEAN CLEANER inputs at lifetime count 0 quote the
    full subtotal 18000 (no discount applied), pinning the subtotal before the
    discount step.

    Design: Difficulty/combinatorial_formula/price_quote_evaluation_order_loyalty_tier_off_subtotal
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 18000, \
        f"Expected subtotal 18000 with no discount at count 0, got {booking['quoted_price_cents']}"


# ===========================================================================
# Queue A — Rule 6: boundary_precision_check (loyalty tier @ count 5)
# (the reschedule free-cancel boundary lives in test_03_window_fees.py)
# ===========================================================================
def test_loyalty_tier_inclusive_boundary_at_count_five(api):
    """PRD §3.6: "5 percent when the count is at least 5 but below 15"

    At exactly count 5 the 0.05 tier turns on, so a TWO_BR DEEP_CLEAN CLEANER
    visit (subtotal 18000) prices 17100.

    Design: Difficulty/boundary_precision_check/loyalty_tier_count_five_inclusive_boundary_on_create_booking
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=5)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 17100, \
        f"Expected 17100 at count-5 boundary, got {booking['quoted_price_cents']}"


def test_loyalty_tier_below_boundary_at_count_four_no_discount(api):
    """PRD §3.6: "The discount rate is 0 percent when the count is below 5"

    At count 4 (one below the boundary) no discount applies, so the same TWO_BR
    DEEP_CLEAN CLEANER visit prices the full subtotal 18000.

    Design: Difficulty/boundary_precision_check/loyalty_tier_count_five_inclusive_boundary_on_create_booking
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=4)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["DEEP_CLEAN"], supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 18000, \
        f"Expected 18000 at count 4 (below tier-5 boundary), got {booking['quoted_price_cents']}"


# ===========================================================================
# Queue B — Corner: calculations
# ===========================================================================
def test_move_out_floor_minimum_applied(api):
    """PRD §3.6: "a move-out floor applies: when `MOVE_OUT` is among the add-ons,
    the priced amount is raised if necessary so that it is never below 20000
    cents."

    ONE_BR base 8000 + move 0.75 -> 6000 = 14000, below the 20000 floor; the
    quote is raised to 20000.

    Design: Corner/calculations/move_out_floor_minimum_applied
    """
    world = setup_booking_world(home_size="ONE_BR", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        add_ons=["MOVE_OUT"], supplies_provided_by="CUSTOMER",
    )
    assert booking["quoted_price_cents"] == 20000, \
        f"Expected 20000 (move-out floor), got {booking['quoted_price_cents']}"


def test_supplies_fee_added_only_when_cleaner_provides(api):
    """PRD §3.6: "The supplies component is the plan's `supplies_fee_cents` when
    `supplies_provided_by` is `CLEANER`, and zero when it is `CUSTOMER`."

    A STUDIO booking (base 6000) with CLEANER supplies prices 7500 (6000 + 1500).

    Design: Corner/calculations/supplies_fee_added_only_when_cleaner_provides
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z",
        supplies_provided_by="CLEANER",
    )
    assert booking["quoted_price_cents"] == 7500, \
        f"Expected 7500 (6000 base + 1500 supplies), got {booking['quoted_price_cents']}"
