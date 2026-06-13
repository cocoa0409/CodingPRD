"""Pricing engine: tiered stay charge, season surcharge, dual provisional/final
variants, loyalty discount, and add-on recomputation.

Covers difficulty queue dual_variant_calc + combinatorial_formula and corner
calculation claims.
"""
import pytest

from test_helpers import (
    validate_success,
    make_guest_headers,
    make_operator_headers,
    create_add_on_payload,
    setup_base_scenario,
    set_clock,
    create_reservation,
    create_confirmed_reservation,
    create_checked_in_reservation,
    check_out_reservation,
    get_reservation,
    get_guest,
    raise_guest_lifetime_spend_via_prior_stay,
)

OP = make_operator_headers()


# ===========================================================================
# Difficulty: dual_variant_calc / stay_charge_provisional_vs_final_on_early_checkout
# ===========================================================================
def test_provisional_charge_prices_all_requested_nights(api):
    """PRD §3.6: "While the reservation has not yet reached `CHECKED_OUT`, the
    stay charge is computed provisionally over the full requested night count —
    the difference between `check_out_date` and `check_in_date`"

    Design: Difficulty/dual_variant_calc/stay_charge_provisional_vs_final_on_early_checkout
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    # 10 nights: min(nightly 50000, weekly 30000+3*5000=45000, monthly same) = 45000.
    assert res["nights"] == 10
    assert res["stay_charge_cents"] == 45000
    # total = 45000 + tax round_half_up(45000*0.08=3600) = 48600.
    assert res["total_due_cents"] == 48600


def test_final_charge_on_early_checkout_reprices_actual_nights(api):
    """PRD §3.7: "It then re-runs the final stay charge over those `priced_nights`
    and reassembles `total_due_cents` per §3.6; because an early checkout can
    only lower the night count, the reconciled `total_due_cents` is floored at
    `deposit_due_cents` — the deposit is never refunded for an early departure."
    PRD §3.7: "the system sets `actual_check_out_date` to the earlier of the
    booked `check_out_date` and the current clock date, and sets `priced_nights`
    to the larger of 1 and the actual nights stayed."

    Design: Difficulty/dual_variant_calc/stay_charge_provisional_vs_final_on_early_checkout
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_checked_in_reservation(
        site, guest, "2026-08-01", "2026-08-11", checkin_clock="2026-08-01T12:00:00Z")
    set_clock("2026-08-06T12:00:00Z")  # depart after 5 actual nights
    final = check_out_reservation(res)
    assert final["reservation_status"] == "CHECKED_OUT"
    assert final["priced_nights"] == 5
    # 5 nights: min(25000, 0*30000+5*5000=25000, 25000) = 25000; +tax 2000 = 27000.
    assert final["stay_charge_cents"] == 25000
    assert final["total_due_cents"] == 27000


# ===========================================================================
# Difficulty: dual_variant_calc / loyalty_discount_lifetime_tier_vs_trailing_12mo
# ===========================================================================
def test_loyalty_discount_uses_lifetime_spend_tier_at_confirm(api):
    """PRD §3.6: "The **loyalty discount**, `discount_cents`, is frozen onto the
    reservation at confirmation, keyed on the acting guest's `lifetime_spend_cents`
    as of that moment — not on the subtotal."
    PRD §3.6: "a guest at or above 200000 cents (but below 500000) earns 5
    percent; below 200000 cents the discount is 0 percent."

    Design: Difficulty/dual_variant_calc/loyalty_discount_lifetime_tier_vs_trailing_12mo
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2024-01-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 60})
    # Prior 56-night stay -> final total 216000 -> lifetime_spend 216000 (SILVER).
    raise_guest_lifetime_spend_via_prior_stay(
        park, rate_plan, site, guest,
        prior_check_in="2024-01-02", prior_check_out="2024-02-27",
        prior_checkout_clock="2024-02-27T12:00:00Z")
    g = get_guest(guest["id"])
    assert g["lifetime_spend_cents"] == 216000
    # Clock moved >12 months past the prior checkout.
    set_clock("2026-08-01T12:00:00Z")
    confirmed = create_confirmed_reservation(site, guest, "2026-09-05", "2026-09-15")
    # 10 nights -> subtotal 45000, 5% discount = round_half_up(45000*0.05)=2250.
    assert confirmed["discount_cents"] == 2250
    # taxable_base = 45000 - 2250 = 42750; tax = round_half_up(42750*0.08=3420)=3420.
    # total = (45000-2250) + 3420 = 42750 + 3420 = 46170.
    assert confirmed["total_due_cents"] == 46170


def test_loyalty_discount_zero_below_silver_threshold(api):
    """PRD §3.6: "below 200000 cents the discount is 0 percent."
    PRD §3.6: "The **loyalty discount**, `discount_cents`, is frozen onto the
    reservation at confirmation, keyed on the acting guest's `lifetime_spend_cents`
    as of that moment — not on the subtotal."

    Design: Difficulty/dual_variant_calc/loyalty_discount_lifetime_tier_vs_trailing_12mo
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    # Fresh guest, lifetime_spend 0 -> 0% discount.
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    assert confirmed["discount_cents"] == 0
    assert confirmed["total_due_cents"] == 48600


# ===========================================================================
# Difficulty: combinatorial_formula / tiered_decomposition_min_over_three_bucketings
# Corner stub stay_charge_tiered_min_over_three is owned by this instance.
# ===========================================================================
def test_tiered_stay_charge_min_over_three_decompositions(api):
    """PRD §3.6: "The engine forms three candidate prices and takes the cheapest."
    PRD §3.6: "The stay charge is the minimum of the nightly, weekly, and monthly
    candidates."

    Design: Difficulty/combinatorial_formula/tiered_decomposition_min_over_three_bucketings
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    # nightly=50000, weekly=1*30000+3*5000=45000, monthly=0+1*30000+3*5000=45000.
    assert res["nights"] == 10
    assert res["stay_charge_cents"] == 45000


def test_tiered_stay_charge_weekly_block_beats_nightly(api):
    """PRD §3.6: "The weekly candidate decomposes `N` into whole seven-night
    blocks plus a remainder: the number of whole weeks (the integer quotient of
    `N` divided by 7) priced at `weekly_rate_cents`, plus the leftover nights
    (the remainder of `N` divided by 7) priced at `nightly_rate_cents`."
    PRD §3.6: "The stay charge is the minimum of the nightly, weekly, and monthly
    candidates."

    Design: Difficulty/combinatorial_formula/tiered_decomposition_min_over_three_bucketings
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    # Exactly 7 nights: nightly 35000 vs weekly 1*30000+0 = 30000 -> 30000 wins.
    res = create_reservation(site, guest, "2026-08-01", "2026-08-08")
    assert res["nights"] == 7
    assert res["stay_charge_cents"] == 30000


# ===========================================================================
# Difficulty: combinatorial_formula / season_surcharge_round_per_night_then_sum
# ===========================================================================
def test_season_surcharge_rounds_each_night_then_sums(api):
    """PRD §3.6: "each night's surcharge is rounded to whole cents first, and
    only then are the per-night surcharges summed. Summing the raw products and
    rounding once at the end would produce a different total and is incorrect."

    Design: Difficulty/combinatorial_formula/season_surcharge_round_per_night_then_sum
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        rate_plan_overrides={
            "nightly_rate_cents": 4444, "weekly_rate_cents": 999999,
            "monthly_rate_cents": 9999999},
        site_overrides={"label": "B-1", "max_length_of_stay_nights": 30})
    validate_success(
        api.create_season(park["id"],
                          {"name": "PEAK", "start_date": "2026-08-01",
                           "end_date": "2026-08-31", "surcharge_pct": 12.5},
                          OP),
        expected_status=201)
    res = create_reservation(site, guest, "2026-08-10", "2026-08-12")
    assert res["nights"] == 2
    # nightly tier picked: 2*4444 = 8888.
    assert res["stay_charge_cents"] == 8888
    # round_half_up(4444*0.125=555.5)=556 per night; 2 nights = 1112 (not 1111).
    assert res["season_surcharge_cents"] == 1112


def test_season_surcharge_zero_outside_window(api):
    """PRD §3.6: "if no season covers it, that night contributes 0."
    PRD §3.6: "the engine checks whether any season on the park covers that date
    (a season covers date `d` when the season's `start_date` is on or before `d`
    and its `end_date` is on or after `d`)."

    Design: Difficulty/combinatorial_formula/season_surcharge_round_per_night_then_sum
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    validate_success(
        api.create_season(park["id"],
                          {"name": "PEAK", "start_date": "2026-08-01",
                           "end_date": "2026-08-31", "surcharge_pct": 12.5},
                          OP),
        expected_status=201)
    # Reservation entirely in September, outside the August season window.
    res = create_reservation(site, guest, "2026-09-01", "2026-09-04")
    assert res["nights"] == 3
    assert res["season_surcharge_cents"] == 0


# ===========================================================================
# Corner: calculations / addon_recompute_changes_total_and_tax
# ===========================================================================
def test_taxable_addon_recomputes_total_and_tax(api):
    """PRD §3.9: "adding it recomputes the parent reservation's `addon_total_cents`,
    `tax_cents`, and `total_due_cents` and bumps the reservation's `version`."
    PRD §3.6: "the lodging tax `tax_cents` is the larger of 0 and the taxable
    base, multiplied by the park's `tax_rate`, rounded half up to whole cents."

    Design: Corner/calculations/addon_recompute_changes_total_and_tax
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.create_add_on(
        res["id"], create_add_on_payload("PET_FEE", 2000, taxable=True),
        make_guest_headers(guest["id"]))
    validate_success(resp, expected_status=201)
    updated = get_reservation(res["id"])
    assert updated["addon_total_cents"] == 2000
    # taxable_base = 45000 + 2000 = 47000; tax = round_half_up(47000*0.08=3760)=3760.
    assert updated["tax_cents"] == 3760
    # total = (45000+2000) + 3760 = 50760.
    assert updated["total_due_cents"] == 50760


# ===========================================================================
# Corner: calculations / nontaxable_addon_excluded_from_taxable_base
# ===========================================================================
def test_nontaxable_addon_excluded_from_taxable_base(api):
    """PRD §3.6: "form the taxable base as `stay_charge_cents` plus
    `season_surcharge_cents` plus the sum of `amount_cents` across `ACTIVE`
    add-ons whose `taxable` flag is true, minus `discount_cents`"

    Design: Corner/calculations/nontaxable_addon_excluded_from_taxable_base
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.create_add_on(
        res["id"], create_add_on_payload("EXTRA_VEHICLE", 2000, taxable=False),
        make_guest_headers(guest["id"]))
    validate_success(resp, expected_status=201)
    updated = get_reservation(res["id"])
    assert updated["addon_total_cents"] == 2000
    # taxable_base excludes the non-taxable add-on: 45000; tax = round_half_up(3600)=3600.
    assert updated["tax_cents"] == 3600
    # total = (45000+2000) + 3600 = 50600.
    assert updated["total_due_cents"] == 50600
