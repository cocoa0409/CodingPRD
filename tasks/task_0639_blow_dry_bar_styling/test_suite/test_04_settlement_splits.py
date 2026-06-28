"""Settlement: tip split (standalone vs event), tiered commission with event cap,
service-vs-retail commission divergence, prepay debit cascade, derived stylist earnings.

Queue A (Difficulty): dual_variant_calc/dvc_tip_split_standalone_vs_event;
                      dual_variant_calc/dvc_service_vs_retail_commission;
                      combinatorial_formula/cf_commission_tier_min_eventcap;
                      transitive_cascade/tc_settle_prepay_debit_to_stylist_earnings.
Queue B (Corner): section `calculations` (tip rounding, unattributed retail commission);
                  section `cross_cutting_complexity_layers` (derived stylist earnings).
"""
import pytest
from test_helpers import (
    validate_success,
    create_product, setup_completed_standalone, setup_completed_prepay,
    setup_confirmed_block, check_in, start_service, complete_service,
    assert_tip_split_conserved, assert_commission_house_conserved,
    setup_sold_retail_sale, make_stylist_headers, TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


# ─── Queue A: tip split standalone vs event block ─────────────────────────────

def test_standalone_tip_split_70_30(api):
    """PRD §3.10: "For a standalone appointment — one whose `event_block_id` is null — the
    serving stylist keeps seventy percent of the tip directly, with the remaining thirty
    percent routed to the pool; the `stylist_tip_cents` is `tip_cents` multiplied by 0.70
    and rounded half-up to a whole cent, and the `tip_pool_cents` is whatever remains of
    the tip after subtracting that direct share, taken as the exact remainder with no
    second rounding."

    Design: Difficulty/dual_variant_calc/dvc_tip_split_standalone_vs_event
    """
    scenario, appt = setup_completed_standalone(service_price=6000)
    settled = validate_success(api.settle_appointment(appt["id"], {"tip_cents": 1000}, FM), 200)
    assert settled["stylist_tip_cents"] == 700
    assert settled["tip_pool_cents"] == 300
    assert_tip_split_conserved(settled)


def test_event_block_tip_split_50_50(api):
    """PRD §3.10: "For an event-block appointment — one whose `event_block_id` is not null
    — the auto-gratuity context routes a larger share to the pool: the stylist keeps fifty
    percent directly and fifty percent goes to the pool, so `stylist_tip_cents` is
    `tip_cents` multiplied by 0.50 rounded half-up, and `tip_pool_cents` is the exact
    remainder."

    Same tip 1000 on an event-block appointment splits 500/500 (vs 700/300 standalone).

    Design: Difficulty/dual_variant_calc/dvc_tip_split_standalone_vs_event
    """
    ctx = setup_confirmed_block(stylist1_tier="SENIOR")
    appt_id = ctx["appt1"]["id"]
    sty_id = ctx["stylist1"]["id"]
    check_in(appt_id, "ON_TIME")
    start_service(appt_id, sty_id)
    complete_service(appt_id, sty_id)
    settled = validate_success(api.settle_appointment(appt_id, {"tip_cents": 1000}, FM), 200)
    assert settled["stylist_tip_cents"] == 500
    assert settled["tip_pool_cents"] == 500
    assert_tip_split_conserved(settled)


def test_standalone_tip_rounding_half_up(api):
    """PRD §3.10: "the `stylist_tip_cents` is `tip_cents` multiplied by 0.70 and rounded
    half-up to a whole cent, and the `tip_pool_cents` is whatever remains of the tip after
    subtracting that direct share, taken as the exact remainder with no second rounding."

    Tip 1505: round_half_up(1505*0.70 = 1053.5) = 1054; pool = 1505 - 1054 = 451.

    Design: Corner/calculations/calc_tip_split_standalone_rounding
    """
    scenario, appt = setup_completed_standalone(service_price=6000)
    settled = validate_success(api.settle_appointment(appt["id"], {"tip_cents": 1505}, FM), 200)
    assert settled["stylist_tip_cents"] == 1054
    assert settled["tip_pool_cents"] == 451
    assert_tip_split_conserved(settled)


# ─── Queue A: tiered commission with event-rate cap (min) ─────────────────────

def test_event_block_master_commission_capped_to_40pct(api):
    """PRD §3.10: "The base rate is thirty-five percent for a `JUNIOR` stylist, forty-five
    percent for a `SENIOR`, and fifty-five percent for a `MASTER`."
    PRD §3.10: "For an event-block appointment, the effective rate is the lesser of the
    stylist's base rate and the event rate cap of forty percent — so a `SENIOR` or
    `MASTER` working an event is capped at forty percent while a `JUNIOR` keeps thirty-five
    ..."

    MASTER (0.55) on event block, charge 6000 -> min(0.55, 0.40)=0.40 -> commission 2400,
    house 3600.

    Design: Difficulty/combinatorial_formula/cf_commission_tier_min_eventcap
    """
    ctx = setup_confirmed_block(stylist1_tier="MASTER")
    appt_id = ctx["appt1"]["id"]
    sty_id = ctx["stylist1"]["id"]
    check_in(appt_id, "ON_TIME")
    start_service(appt_id, sty_id)
    complete_service(appt_id, sty_id)
    settled = validate_success(api.settle_appointment(appt_id, {"tip_cents": 0}, FM), 200)
    assert settled["service_charge_cents"] == 6000
    assert settled["commission_amount_cents"] == 2400
    assert settled["house_amount_cents"] == 3600
    assert_commission_house_conserved(settled)


def test_standalone_master_commission_full_55pct(api):
    """PRD §3.10: "The base rate is thirty-five percent for a `JUNIOR` stylist, forty-five
    percent for a `SENIOR`, and fifty-five percent for a `MASTER`."
    PRD §3.10: "and for a standalone appointment the effective rate is simply the base
    rate."

    Standalone MASTER, charge 6000 -> 0.55 -> commission 3300 (vs 2400 event-capped).

    Design: Difficulty/combinatorial_formula/cf_commission_tier_min_eventcap
    """
    scenario, appt = setup_completed_standalone(service_price=6000, commission_tier="MASTER")
    settled = validate_success(api.settle_appointment(appt["id"], {"tip_cents": 0}, FM), 200)
    assert settled["commission_amount_cents"] == 3300
    assert settled["house_amount_cents"] == 2700
    assert_commission_house_conserved(settled)


# ─── Queue A: service (tiered) vs retail (flat) commission divergence ─────────

def test_service_commission_master_3300(api):
    """PRD §3.10: "The base rate is thirty-five percent for a `JUNIOR` stylist, forty-five
    percent for a `SENIOR`, and fifty-five percent for a `MASTER`."
    PRD §3.10: "The `commission_amount_cents` is the appointment's final
    `service_charge_cents` (including any late fee already folded in at check-in)
    multiplied by the effective rate and rounded half-up to a whole cent ..."

    A MASTER service commission on a 6000-cent standalone charge is 3300 (0.55), distinct
    from the same stylist's flat retail commission of 600 on a 6000-cent gross.

    Design: Difficulty/dual_variant_calc/dvc_service_vs_retail_commission
    """
    scenario, appt = setup_completed_standalone(service_price=6000, commission_tier="MASTER")
    settled = validate_success(api.settle_appointment(appt["id"], {"tip_cents": 0}, FM), 200)
    assert settled["commission_amount_cents"] == 3300


def test_retail_commission_flat_600_for_same_gross(api):
    """PRD §3.12: "otherwise it is the `gross_cents` multiplied by the product's
    `retail_commission_pct`, rounded half-up to a whole cent."
    PRD §3.12: "This retail commission is conceptually the same payout as service
    commission but computed on a different basis — a flat product rate on the sale's gross
    rather than a tiered rate on a service charge — so the same dollar gross can produce a
    different commission than a service of equal value would."

    6000 gross * 0.10 = 600 (flat), vs 3300 for the MASTER service of equal dollar value.

    Design: Difficulty/dual_variant_calc/dvc_service_vs_retail_commission
    """
    prod = create_product(sku="SH-01", name="Shampoo", unit_price_cents=6000,
                          initial_stock=10, retail_commission_pct=0.10)
    from test_helpers import create_member, create_stylist
    member = create_member(full_name="Walk In")
    stylist = create_stylist(full_name="Mia Master", commission_tier="MASTER")
    sale = validate_success(api.create_retail_sale(
        {"product_id": prod["id"], "member_id": member["id"], "quantity": 1,
         "attributed_stylist_id": stylist["id"]}, FD), 201)
    assert sale["gross_cents"] == 6000
    assert sale["retail_commission_cents"] == 600


def test_retail_commission_unattributed_is_zero(api):
    """PRD §3.12: "If no stylist is attributed, the `retail_commission_cents` is zero ..."

    Design: Corner/calculations/calc_retail_commission_unattributed_zero
    """
    prod = create_product(sku="UN-01", name="Unattr", unit_price_cents=5000, initial_stock=10)
    from test_helpers import create_member
    member = create_member(full_name="Buyer")
    sale = validate_success(api.create_retail_sale(
        {"product_id": prod["id"], "member_id": member["id"], "quantity": 2}, FD), 201)
    assert sale["gross_cents"] == 10000
    assert sale["retail_commission_cents"] == 0


# ─── Queue A: PREPAY settle debits member, cascades to stylist earnings ───────

def test_settle_prepay_debits_member_and_lifts_stylist_earnings(api):
    """PRD §3.10: "If the appointment was `PREPAY`, the member's `prepay_balance_cents` is
    debited by the `service_charge_cents`."
    PRD §3.10: "The serving stylist's `earned_commission_cents` and `earned_tips_cents`
    are then reconciled to fold in this newly settled appointment."

    Member with 10000 prepay; SENIOR PREPAY charge 6000: after settle, prepay 4000 and
    SENIOR commission 2700 lifts earned_commission_cents.

    Design: Difficulty/transitive_cascade/tc_settle_prepay_debit_to_stylist_earnings
    """
    scenario, appt = setup_completed_prepay(prepay_amount=10000, service_price=6000,
                                            commission_tier="SENIOR")
    settled = validate_success(api.settle_appointment(appt["id"], {"tip_cents": 0}, FM), 200)
    assert settled["service_charge_cents"] == 6000

    member_after = validate_success(api.get_member(scenario["member"]["id"], FD), 200)
    assert member_after["prepay_balance_cents"] == 4000

    stylist_after = validate_success(api.get_stylist(scenario["stylist"]["id"], FD), 200)
    assert stylist_after["earned_commission_cents"] == 2700


def test_settle_prepay_debit_tracks_actual_charge(api):
    """PRD §3.10: "If the appointment was `PREPAY`, the member's `prepay_balance_cents` is
    debited by the `service_charge_cents`."
    PRD §3.10: "The serving stylist's `earned_commission_cents` and `earned_tips_cents` are
    then reconciled to fold in this newly settled appointment."

    With a 5000 charge and 8000 prepay, settle debits exactly 5000 (leaving 3000) and lifts
    the SENIOR stylist's earned_commission_cents to round(5000*0.45)=2250 — the same
    two-hop cascade from one settle, at a different charge amount than the 6000 case.

    Design: Difficulty/transitive_cascade/tc_settle_prepay_debit_to_stylist_earnings
    """
    scenario, appt = setup_completed_prepay(prepay_amount=8000, service_price=5000,
                                            commission_tier="SENIOR")
    settled = validate_success(api.settle_appointment(appt["id"], {"tip_cents": 0}, FM), 200)
    assert settled["service_charge_cents"] == 5000

    member_after = validate_success(api.get_member(scenario["member"]["id"], FD), 200)
    assert member_after["prepay_balance_cents"] == 3000

    stylist_after = validate_success(api.get_stylist(scenario["stylist"]["id"], FD), 200)
    assert stylist_after["earned_commission_cents"] == 2250


# ─── Queue B: derived stylist earnings after a standalone settlement ──────────

def test_derived_stylist_earnings_after_standalone_settlement(api):
    """PRD §3.3: "A stylist's `earned_commission_cents` is the sum of
    `commission_amount_cents` over their settled appointments ... `earned_tips_cents` is
    the sum of `stylist_tip_cents` over their settled appointments."

    SENIOR standalone charge 6000, tip 1000: commission 2700, direct tip 700.

    Design: Corner/cross_cutting_complexity_layers/derived_stylist_earnings_after_settlement
    """
    scenario, appt = setup_completed_standalone(service_price=6000, commission_tier="SENIOR")
    validate_success(api.settle_appointment(appt["id"], {"tip_cents": 1000}, FM), 200)
    stylist_after = validate_success(api.get_stylist(scenario["stylist"]["id"], FD), 200)
    assert stylist_after["earned_commission_cents"] == 2700
    assert stylist_after["earned_tips_cents"] == 700
