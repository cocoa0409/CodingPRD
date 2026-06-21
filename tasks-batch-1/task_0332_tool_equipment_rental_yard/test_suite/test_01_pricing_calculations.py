"""Tiered rental pricing, dual estimate/final variants, and final-total composition.

Covers difficulty rules dual_variant_calc and combinatorial_formula, plus the
corner-design calculation instances that exercise the tiered rental charge,
delivery fee, cleaning fee, service threshold, and waiver netting.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_yard, create_reservation, setup_picked_up_agreement,
    find_agreement_for_reservation, return_agreement, inspect,
    setup_returned_pending_inspection, set_clock,
    api_client, TEST_USERS,
)

YM = TEST_USERS["yard_manager_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ─── dual_variant_calc ────────────────────────────────────────────

def test_estimate_bills_full_planned_interval(api):
    """PRD §3.8: "runs at reservation confirm and writes estimated_rental_cents;
    its interval is the full planned [rental_start_date, rental_end_date],
    assuming an on-time return and ignoring any overdue or late component."

    Design: Difficulty/dual_variant_calc/rental_charge_estimate_vs_final_diverge_on_overdue
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    # 10 billed days = one 7-day week (20000) + 3 loose days (3*4000) = 32000.
    assert r["estimated_rental_cents"] == 32000
    assert r["estimated_total_cents"] == 32000


def test_final_excludes_overdue_days_billed_as_late_fee(api):
    """PRD §3.8: "its interval runs from actual_start_date to the earlier of
    actual_return_date and scheduled_end_date — overdue days are deliberately
    excluded from the rental rate here and billed instead as a late fee."
    PRD §3.8: "The late_fee_cents is the overdue-day count multiplied by
    daily_rate_cents multiplied by late_fee_multiplier, rounded half up to whole
    cents."

    Design: Difficulty/dual_variant_calc/rental_charge_estimate_vs_final_diverge_on_overdue
    """
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    ag = return_agreement(ctx["agreement"]["id"], "2026-06-13T09:00:00.000Z")
    # final interval capped at scheduled_end 06-10 => 10 days => 32000.
    assert ag["final_rental_cents"] == 32000
    # 3 overdue days (06-11..06-13) * 4000 * 1.5 = 18000.
    assert ag["late_fee_cents"] == 18000
    assert ag["final_rental_cents"] + ag["late_fee_cents"] == 50000
    assert ctx["reservation"]["estimated_total_cents"] == 32000


def test_account_balance_after_deposit_hold_only(api):
    """PRD §2.9: "Whenever any ledger entry is inserted, the server recomputes
    the balance from scratch as the sum of amount_cents across all
    AccountLedgerEntry rows whose contractor_account_id equals the account's id,
    taken in created_at ascending order."
    PRD §3.4: "the server posts a DEPOSIT_HOLD ledger entry for the deposit
    amount and recomputes the account's outstanding_balance_cents."

    Design: Difficulty/dual_variant_calc/account_balance_actual_vs_credit_projection
    """
    ctx = setup_yard()
    create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                       rental_start_date="2026-06-01", rental_end_date="2026-06-10",
                       damage_waiver_opted=True)
    acct = validate_success(
        api.get_contractor_account(ctx["account"]["id"], YM), 200)
    # Only the +50000 deposit hold has posted.
    assert acct["outstanding_balance_cents"] == 50000


def test_estimated_total_includes_waiver_projection(api):
    """PRD §3.4: "The estimated_total_cents is the sum of estimated_rental_cents,
    the estimated waiver amount, and delivery_fee_cents. The estimated waiver
    amount is damage_waiver_daily_cents multiplied by the planned billed days when
    damage_waiver_opted is true, and 0 otherwise."

    Design: Difficulty/dual_variant_calc/account_balance_actual_vs_credit_projection
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-10",
                           damage_waiver_opted=True)
    # rental 32000 + waiver (1500 * 10 days) 15000 + delivery 0 = 47000.
    assert r["estimated_total_cents"] == 47000


# ─── combinatorial_formula ────────────────────────────────────────

def test_tiered_best_rate_cap_collapses_to_four_week_block(api):
    """PRD §3.8: "A best-rate guard then ensures no partial block costs more than
    the next whole block, applied in a pinned order: first, if pricing the loose
    days at the daily rate exceeds weekly_rate_cents, charge one week instead of
    those loose days; second, after that adjustment, if pricing the resulting
    weeks within the current twenty-eight-day remainder exceeds
    four_week_rate_cents, charge one four-week block instead."

    Design: Difficulty/combinatorial_formula/rental_charge_tiered_best_rate_cap_selection
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-27")
    # 27 days greedy: 0*4wk + 3wk + 6d. Caps collapse to one 4-week block = 60000.
    assert r["estimated_rental_cents"] == 60000


def test_tiered_cap_not_naive_block_sum(api):
    """PRD §3.8: "the rental charge is the sum of these three products. A best-rate
    guard then ensures no partial block costs more than the next whole block".

    Design: Difficulty/combinatorial_formula/rental_charge_tiered_best_rate_cap_selection
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-27")
    # Naive 3*20000 + 6*4000 = 84000 must NOT be charged.
    assert r["estimated_rental_cents"] != 84000
    assert r["estimated_rental_cents"] == 60000


def test_final_total_deposit_subtracted_after_damage_components(api):
    """PRD §3.8: "The final_total_cents is the sum of the rental, waiver, late fee,
    fuel refill, cleaning, and net damage components, with the deposit refund
    subtracted. The deposit is always fully refunded — damage is posted as its own
    separate positive charge and is never netted against the deposit".

    Design: Difficulty/combinatorial_formula/final_total_pinned_evaluation_order_deposit_after_damage
    """
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False})
    return_agreement(ctx["agreement"]["id"], "2026-06-10T09:00:00.000Z")
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=25,
            cleanliness="DIRTY", damage_assessed_cents=25000)
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    # rental 32000 + fuel (15*200=3000) + cleaning 8000 + damage 25000 - deposit 50000 = 18000.
    assert ag["final_total_cents"] == 18000
    assert ag["agreement_state"] == "CLOSED_WITH_DAMAGE"


def test_damage_inspection_computes_fuel_and_net_damage(api):
    """PRD §3.8: "The fuel_refill_cents is those capped missing liters multiplied
    by the rate card's fuel_refill_cents_per_liter."
    PRD §3.8: "The net_damage_cents is zero when the reservation's
    damage_waiver_opted was true and equals the gross otherwise."

    Design: Difficulty/combinatorial_formula/final_total_pinned_evaluation_order_deposit_after_damage
    """
    ctx = setup_picked_up_agreement(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False})
    return_agreement(ctx["agreement"]["id"], "2026-06-10T09:00:00.000Z")
    ins = inspect(ctx["agreement"]["id"], return_fuel_level_liters=25,
                  cleanliness="DIRTY", damage_assessed_cents=25000)
    assert ins["fuel_refill_cents"] == 3000
    assert ins["net_damage_cents"] == 25000


# ─── corner: calculations ─────────────────────────────────────────

def test_single_loose_day_billed_at_daily_rate(api):
    """PRD §3.8: "each loose day at daily_rate_cents; the rental charge is the sum
    of these three products."

    Design: Corner/calculations/rental_charge_single_loose_day
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-01")
    assert r["estimated_rental_cents"] == 4000


def test_exact_week_boundary_bills_weekly_rate(api):
    """PRD §3.8: "Starting from the billed-day count, the server takes as many
    whole twenty-eight-day blocks as fit, then as many whole seven-day blocks as
    fit in the remainder, and the days still left over are loose days. Each
    twenty-eight-day block is priced at four_week_rate_cents, each seven-day block
    at weekly_rate_cents".

    Design: Corner/calculations/rental_charge_exact_week_boundary
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-07")
    # 7 days = one weekly block = 20000 (not 7*4000=28000).
    assert r["estimated_rental_cents"] == 20000


def test_delivery_fee_heavy_equipment_category(api):
    """PRD §3.4: "The delivery fee is a flat amount keyed by the catalog item's
    category when fulfillment_method is DELIVERY, and 0 for PICKUP: 0 cents for a
    HAND_TOOL, 2500 cents for a POWER_TOOL, and 12000 cents for a HEAVY_EQUIPMENT."

    Design: Corner/calculations/delivery_fee_by_category_heavy_equipment
    """
    ctx = setup_yard(item_overrides={"requires_delivery": True})
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           fulfillment_method="DELIVERY",
                           rental_start_date="2026-06-01", rental_end_date="2026-06-07")
    assert r["delivery_fee_cents"] == 12000
    # rental (7 days => 20000) + waiver 0 + delivery 12000 = 32000.
    assert r["estimated_total_cents"] == 32000


def test_waiver_nets_damage_to_zero_unit_still_out_of_service(api):
    """PRD §3.6: "when damage was assessed but the contractor had opted into the
    waiver, the net damage charge is zero and the agreement still closes as CLOSED
    rather than CLOSED_WITH_DAMAGE, yet the unit still goes OUT_OF_SERVICE with a
    DAMAGE_REPAIR ticket because the damage physically occurred."

    Design: Corner/calculations/damage_waiver_nets_damage_to_zero_unit_still_out_of_service
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10",
        "damage_waiver_opted": True})
    ins = inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
                  cleanliness="CLEAN", damage_assessed_cents=25000)
    assert ins["net_damage_cents"] == 0
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    assert ag["agreement_state"] == "CLOSED"
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "OUT_OF_SERVICE"


def test_service_threshold_auto_out_of_service_on_clean_return(api):
    """PRD §3.6: "whenever damage_assessed_cents is greater than 0, or the unit's
    lifetime_rental_days plus billed days reaches or exceeds service_due_at_days —
    the unit moves ON_RENT → OUT_OF_SERVICE, its version increments, and the server
    auto-creates a MaintenanceTicket in OPEN ... whose reason is ... SCHEDULED_SERVICE
    when the trigger was the service threshold."

    Design: Corner/calculations/service_threshold_auto_out_of_service_on_return
    """
    ctx = setup_returned_pending_inspection(
        unit_overrides={"service_due_at_days": 5},
        reservation_overrides={"rental_start_date": "2026-06-01",
                               "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=0)
    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], YM), 200)
    assert unit["availability_state"] == "OUT_OF_SERVICE"
    assert unit["lifetime_rental_days"] == 10
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    assert ag["agreement_state"] == "CLOSED"


def test_cleaning_fee_applied_when_dirty(api):
    """PRD §3.8: "then the cleaning amount, which is cleaning_fee_cents when
    cleanliness is DIRTY and 0 otherwise".

    Design: Corner/calculations/cleaning_fee_applied_when_dirty
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10",
        "damage_waiver_opted": False})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="DIRTY", damage_assessed_cents=0)
    ag = validate_success(
        api.get_rental_agreement(ctx["agreement"]["id"], YM), 200)
    # rental 32000 + cleaning 8000 - deposit 50000 = -10000.
    assert ag["final_total_cents"] == -10000
    assert ag["agreement_state"] == "CLOSED"


# ─── corner: cross-cutting complexity layers ──────────────────────

def test_four_week_block_exact_28_days(api):
    """PRD §3.8: "the server takes as many whole twenty-eight-day blocks as fit ...
    Each twenty-eight-day block is priced at four_week_rate_cents".

    Design: Corner/cross_cutting_complexity_layers/tiered_pricing_four_week_block_exact
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-28")
    # 28 days = one four-week block = 60000.
    assert r["estimated_rental_cents"] == 60000


def test_balance_reconciles_after_payment(api):
    """PRD §2.9: "Charges and holds — DEPOSIT_HOLD, RENTAL_CHARGE, FUEL_CHARGE,
    CLEANING_CHARGE, LATE_FEE, and DAMAGE_CHARGE — are positive and increase the
    balance; refunds and payments — DEPOSIT_REFUND and PAYMENT — are negative and
    decrease it."

    Design: Corner/cross_cutting_complexity_layers/derived_field_balance_after_payment
    """
    from test_helpers import make_contractor_headers, create_payment_payload
    ctx = setup_yard()
    create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                       rental_start_date="2026-06-01", rental_end_date="2026-06-10")
    api.create_payment(ctx["account"]["id"], create_payment_payload(-20000),
                       make_contractor_headers(ctx["account"]["id"]))
    acct = validate_success(
        api.get_contractor_account(ctx["account"]["id"], YM), 200)
    # +50000 hold, -20000 payment = 30000.
    assert acct["outstanding_balance_cents"] == 30000


# ─── corner: consistency model ────────────────────────────────────

def test_estimate_visible_on_create_response(api):
    """PRD §3.4: "On confirmation the reservation enters the CONFIRMED state and
    the server computes a forward-looking estimated_rental_cents from the full
    planned interval".

    Design: Corner/consistency_model/immediate_visibility_of_estimate_on_create
    """
    ctx = setup_yard()
    r = create_reservation(ctx["account"]["id"], ctx["item"]["id"], ctx["unit"]["id"],
                           rental_start_date="2026-06-01", rental_end_date="2026-06-07")
    # 7 days = one weekly block = 20000, present on the create response itself.
    assert r["estimated_rental_cents"] == 20000
