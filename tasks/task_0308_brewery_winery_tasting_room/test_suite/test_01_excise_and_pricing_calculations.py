"""Excise accrual, loyalty, shipment/POS/distribution pricing calculations.

Translates difficulty queue A (dual_variant_calc, combinatorial_formula) and the
non-stub calculation corners. Every literal expected value is copied verbatim
from the design indices; none is recomputed here.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    create_member_payload, create_membership_payload, create_shipment_payload,
    create_tasting_order_payload, bottle_line, create_distribution_order_payload,
    setup_active_product, setup_club_ready, set_clock,
    create_winery, create_batch_in_bottling, create_product,
    bottle_run, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]


# ─── dual_variant_calc ─────────────────────────────────

def test_excise_wine_tier1_vs_beer_per_barrel_diverge(api):
    """PRD §3.3: "For a `WINE` batch the rate is keyed on alcohol by volume: when
    the batch's `abv_percent` is at most 14.0, the rate is 107 cents per gallon".
    PRD §3.3: "For a `BEER` batch the gallons are first converted to barrels by
    dividing the removal gallons by 31.0 gallons per barrel, and the excise in
    cents is that barrel count multiplied by 1800 cents per barrel, rounded half
    up to whole cents; beer ignores ABV entirely."

    Same physical removal (100x750ml), divergent excise: WINE tier1 2120c vs
    BEER per-barrel 1150c, both booked onto winery.excise_tax_owed_cents.

    Design: Difficulty/dual_variant_calc/excise_wine_tier_vs_beer_barrel_diverge
    """
    set_clock("2026-06-15T00:00:00Z")
    w_wine = create_winery(name="Wine Co", ttb_permit_number="WINE-1")
    w_beer = create_winery(name="Beer Co", ttb_permit_number="BEER-1")

    b_wine = create_batch_in_bottling(w_wine["id"],
                                      batch_overrides={"beverage_class": "WINE", "abv_percent": 13.5})
    b_beer = create_batch_in_bottling(w_beer["id"],
                                      batch_overrides={"beverage_class": "BEER", "abv_percent": 5.0})

    p_wine = create_product(w_wine["id"], b_wine["id"], sku="WS1")
    p_beer = create_product(w_beer["id"], b_beer["id"], sku="BS1")

    bottle_run(b_wine["id"], p_wine["id"], 100)
    bottle_run(b_beer["id"], p_beer["id"], 100)

    wine = get_success_data(api.get_winery(w_wine["id"], CO))
    beer = get_success_data(api.get_winery(w_beer["id"], CO))
    assert wine["excise_tax_owed_cents"] == 2120, wine["excise_tax_owed_cents"]
    assert beer["excise_tax_owed_cents"] == 1150, beer["excise_tax_owed_cents"]


def test_loyalty_membership_balance_equals_winery_liability_single_membership(api):
    """PRD §3.7: "The points earned are the net spend in cents divided by 100 cents
    per point, taken as a floor to whole points, then multiplied by the tier
    multiplier; this is the `loyalty_points_earned` added to the membership's
    `loyalty_points`."
    PRD §3.7: "The winery's `loyalty_point_liability` is, at all times, the sum of
    `loyalty_points` across every membership of that winery — equal to a single
    membership's balance only in a winery with exactly one membership."

    A PLATINUM release of 12 @ 5000c (net 49200c) mints floor(492)*3 = 1476 points;
    with one earning membership the winery liability equals that balance, 1476.

    Design: Difficulty/dual_variant_calc/loyalty_membership_balance_vs_winery_liability
    """
    winery, product, release, member, membership = setup_club_ready(
        pool_bottles=12, per_member_cap=12, tier="PLATINUM",
        bottled_bottles=50, list_price_cents=5000)
    shipment = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 12), CLM))
    released = validate_success(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM), 200)
    assert released["status"] == "RELEASED"

    ms = get_success_data(api.get_membership(membership["id"], CLM))
    w = get_success_data(api.get_winery(winery["id"], CO))
    assert ms["loyalty_points"] == 1476, ms["loyalty_points"]
    assert w["loyalty_point_liability"] == 1476, w["loyalty_point_liability"]


# ─── combinatorial_formula ─────────────────────────────

def test_shipment_pricing_kicker_then_cap_platinum(api):
    """PRD §3.7: "if `requested_bottles` is at least 12, a volume kicker of 0.05 is
    added to that base percentage; the resulting effective percentage is then
    capped at a maximum of 0.18 — the cap applied last, after the kicker."
    PRD §3.7: "The `discount_cents` is the `subtotal_cents` multiplied by that
    fully resolved effective percentage, rounded half up to whole cents in a
    single rounding step rather than per component."

    PLATINUM 12 bottles @ 5000c: base 0.15 + 0.05 = 0.20 capped to 0.18 on a
    60000c subtotal -> discount 10800c, total 49200c.

    Design: Difficulty/combinatorial_formula/shipment_pricing_kicker_then_cap_mode_a
    """
    winery, product, release, member, membership = setup_club_ready(
        pool_bottles=12, per_member_cap=12, tier="PLATINUM",
        bottled_bottles=50, list_price_cents=5000)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 12), CLM), 201)
    assert shipment["subtotal_cents"] == 60000, shipment["subtotal_cents"]
    assert shipment["discount_cents"] == 10800, shipment["discount_cents"]
    assert shipment["total_cents"] == 49200, shipment["total_cents"]


def test_pos_total_round_per_line_then_sum_gold(api):
    """PRD §3.9: "this rounding-each-line-then-summing order is mandatory and can
    differ by cents from summing raw then rounding."
    PRD §3.9: "When a member is attached, the `member_discount_cents` is the bottle
    subtotal — the sum of the rounded line totals over the `BOTTLE` lines only —
    multiplied by the membership's tier discount percentage (0.05 for `SILVER`,
    0.10 for `GOLD`, 0.15 for `PLATINUM`), rounded half up once".

    Three BOTTLE lines of 333c sum to 999c; GOLD discount rounds once on the
    bottle subtotal -> 100c, total 899c.

    Design: Difficulty/combinatorial_formula/pos_total_round_per_line_then_sum_mode_b
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 333})
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], full_name="Gil Gold", email="gil@x.com",
                              date_of_birth="1990-01-01T00:00:00Z"), CLM))
    member = get_success_data(api.transition_member(member["id"], {"action": "ACTIVATE"}, CLM))
    membership = get_success_data(api.create_membership(
        create_membership_payload(winery["id"], member["id"], tier="GOLD"), CLM))
    get_success_data(api.transition_membership(membership["id"], {"action": "ACTIVATE"}, CLM))

    line_items = [bottle_line(product["id"], 1) for _ in range(3)]
    order = validate_success(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], line_items, member_id=member["id"],
                                     guest_age_verified=True), TRS), 201)
    assert order["subtotal_cents"] == 999, order["subtotal_cents"]
    assert order["member_discount_cents"] == 100, order["member_discount_cents"]
    assert order["total_cents"] == 899, order["total_cents"]


def test_distribution_invoice_freight_keyed_on_base(api):
    """PRD §3.11: "the wholesale base is that gross multiplied by the wholesale
    percentage of 0.50, rounded half up to whole cents; then a freight tier is
    selected on the wholesale base (not on the gross) — if the rounded wholesale
    base is at least 50000 cents, freight is 1500 cents, otherwise freight is
    2500 cents; and the `wholesale_total_cents` is the wholesale base plus that
    freight."

    1 case @8500c: gross 102000, base 51000 >= 50000 -> freight 1500 -> total 52500.

    Design: Difficulty/combinatorial_formula/distribution_invoice_freight_keyed_on_base_mode_c
    """
    winery, batch, product = setup_active_product(
        bottled_bottles=0, product_overrides={"list_price_cents": 8500})
    dist = validate_success(api.create_distribution_order(
        create_distribution_order_payload(winery["id"], product["id"], case_count=1), CO), 201)
    assert dist["bottles_ordered"] == 12, dist["bottles_ordered"]
    assert dist["wholesale_total_cents"] == 52500, dist["wholesale_total_cents"]


# ─── Corner: calculations (non-stub) ───────────────────

def test_cider_excise_flat_per_gallon(api):
    """PRD §3.3: "For a `CIDER` batch the excise is a flat 23 cents per gallon —
    the removal gallons multiplied by 23, rounded half up to whole cents — and is
    likewise not keyed on ABV."

    100x750ml = 19.812913 gal at 23c/gal -> round_half_up = 456c.

    Design: Corner/calculations/cider_excise_flat_per_gallon
    """
    winery = create_winery(name="Cdr Co", ttb_permit_number="CDR-1")
    batch = create_batch_in_bottling(winery["id"], batch_overrides={"beverage_class": "CIDER", "abv_percent": 6.0})
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 100)
    w = get_success_data(api.get_winery(winery["id"], CO))
    assert w["excise_tax_owed_cents"] == 456, w["excise_tax_owed_cents"]


def test_wine_excise_tier2_above_14pct(api):
    """PRD §3.3: "when the `abv_percent` is strictly greater than 14.0, the rate is
    157 cents per gallon. The wine excise in cents is the removal gallons multiplied
    by the selected per-gallon rate, rounded half up to a whole number of cents."

    WINE abv 15.5 selects tier2 157c/gal: 19.812913 gal -> round_half_up = 3111c.

    Design: Corner/calculations/wine_excise_tier2_above_14pct
    """
    winery = create_winery(name="W2 Co", ttb_permit_number="W2-1")
    batch = create_batch_in_bottling(winery["id"], batch_overrides={"beverage_class": "WINE", "abv_percent": 15.5})
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 100)
    w = get_success_data(api.get_winery(winery["id"], CO))
    assert w["excise_tax_owed_cents"] == 3111, w["excise_tax_owed_cents"]


def test_distribution_freight_low_below_threshold(api):
    """PRD §3.11: "if the rounded wholesale base is at least 50000 cents, freight is
    1500 cents, otherwise freight is 2500 cents; and the `wholesale_total_cents`
    is the wholesale base plus that freight."

    1 case @8000c: gross 96000, base 48000 < 50000 -> freight 2500 -> total 50500.

    Design: Corner/calculations/distribution_freight_low_below_threshold
    """
    winery, batch, product = setup_active_product(
        bottled_bottles=0, product_overrides={"list_price_cents": 8000})
    dist = validate_success(api.create_distribution_order(
        create_distribution_order_payload(winery["id"], product["id"], case_count=1), CO), 201)
    assert dist["wholesale_total_cents"] == 50500, dist["wholesale_total_cents"]


def test_event_deposit_computed(api):
    """PRD §3.10: "For an event, a deposit is required: the `deposit_cents` is the
    `party_size` multiplied by 1500 cents per guest; for a non-event the
    `deposit_cents` is zero."

    is_event=true, party_size 4 -> deposit_cents = 4*1500 = 6000.

    Design: Corner/calculations/event_deposit_computed
    """
    from test_helpers import create_reservation_payload
    winery = create_winery(name="Ev Co", ttb_permit_number="EV-1")
    res = validate_success(api.create_reservation(
        create_reservation_payload(winery["id"], table_code="PATIO", party_size=4,
                                   starts_at="2026-06-20T18:00:00Z",
                                   ends_at="2026-06-20T20:00:00Z", is_event=True), TRS), 201)
    assert res["deposit_cents"] == 6000, res["deposit_cents"]
    assert res["status"] == "REQUESTED"


def test_derived_winery_excise_reconciles_after_two_runs(api):
    """PRD §3.3: "In the third hop the premises books the tax: the winery's
    `bottled_taxpaid_volume_gallons` increases by the removal gallons, and the
    winery's `excise_tax_owed_cents` increases by the excise this run accrues."
    PRD §3.3: "the rate is 107 cents per gallon."

    Two WINE tier1 runs of 100x750ml each accrue 2120c; winery reconciles to 4240c.

    Design: Corner/cross_cutting_complexity_layers/derived_winery_excise_reconciles_after_two_runs
    """
    winery = create_winery(name="Rc Co", ttb_permit_number="RC-1")
    batch = create_batch_in_bottling(winery["id"], batch_overrides={"beverage_class": "WINE", "abv_percent": 13.5})
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 100)
    bottle_run(batch["id"], product["id"], 100)
    w = get_success_data(api.get_winery(winery["id"], CO))
    assert w["excise_tax_owed_cents"] == 4240, w["excise_tax_owed_cents"]
