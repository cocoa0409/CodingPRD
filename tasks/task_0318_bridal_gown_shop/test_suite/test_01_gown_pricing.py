"""Gown-order and alteration pricing: quoted vs final variants, rounding order,
size/rush surcharges, and the payment-plan waterfall schedule.

Covers difficulty rules dual_variant_calc and combinatorial_formula, plus the
corner calculations section.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_draft_order, create_active_accessory, create_plan,
    create_received_order, create_ordered_order,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, CLERK, SEAMSTRESS, get_plan


# ─── dual_variant_calc / gown_total_quoted_vs_final_diverges_on_accessories ──

def test_quoted_total_stamped_at_draft_creation(api):
    """PRD §3.3: "The quoted total stamped at creation is exactly this gown subtotal:
    no accessories exist yet at draft creation, so the quoted estimate carries no
    accessory contribution." Base 200000, size 22 (>=20 upcharge), rush -> 290000.

    Design: Difficulty/dual_variant_calc/gown_total_quoted_vs_final_diverges_on_accessories
    """
    res = api.create_gown_order(
        {"gown_style_code": "ELEGANCE", "ordered_size": 22, "base_price_cents": 200000,
         "standard_lead_days": 90, "is_rush": True},
        CONSULTANT,
    )
    order = validate_success(res, 201)
    assert order["quoted_total_cents"] == 290000, (
        f"quoted_total_cents should be 290000, got {order['quoted_total_cents']}"
    )


def test_final_total_diverges_from_quoted_with_active_accessory(api):
    """PRD §3.4: "That variant recomputes the gown subtotal exactly as at quote time ...
    and then adds the sum of `price_cents` across every `ACTIVE` accessory add-on on the
    order". A VEIL of 15000 makes final_total_cents 305000, different from quoted 290000.

    Design: Difficulty/dual_variant_calc/gown_total_quoted_vs_final_diverges_on_accessories
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    create_active_accessory(order["id"], accessory_type="VEIL", price_cents=15000)
    create_plan(order["id"], term_installments=5, deposit_cents=152500)
    validate_success(api.submit_gown_order(order["id"], CONSULTANT), 200)
    received = validate_success(api.receive_gown_order(order["id"], MANAGER), 200)

    assert received["quoted_total_cents"] == 290000
    assert received["final_total_cents"] == 305000, (
        f"final_total_cents should be 305000, got {received['final_total_cents']}"
    )
    assert received["final_total_cents"] != received["quoted_total_cents"]


# ─── dual_variant_calc / alteration_estimate_vs_actual_diverges_on_refits ────

def test_alteration_estimated_cost_at_creation(api):
    """PRD §3.5: "The labor rate is 120 cents per minute, so the estimate is
    `estimated_labor_minutes` multiplied by 120 cents. No refit surcharge applies to
    the estimate because `refitting_count` is 0 at creation." 60 minutes -> 7200.

    Design: Difficulty/dual_variant_calc/alteration_estimate_vs_actual_diverges_on_refits
    """
    order, _ = create_received_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    res = api.create_alteration_job(
        {"gown_order_id": order["id"], "estimated_labor_minutes": 60}, SEAMSTRESS)
    job = validate_success(res, 201)
    assert job["estimated_cost_cents"] == 7200, (
        f"estimated_cost_cents should be 7200, got {job['estimated_cost_cents']}"
    )
    assert job["refitting_count"] == 0


def test_alteration_final_cost_with_refit_surcharge(api):
    """PRD §3.5: "That figure is the realized labor cost — `actual_labor_minutes`
    multiplied by 120 cents per minute — scaled by a refit multiplier of one plus ten
    percent for each refitting round, that is, one plus the product of 0.10 and
    `refitting_count`; the whole product is then rounded up to a whole cent". With
    actual 90 minutes and refitting_count 2: ceil(90*120*1.2) = 12960.

    Design: Difficulty/dual_variant_calc/alteration_estimate_vs_actual_diverges_on_refits
    """
    order, _ = create_received_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    job = validate_success(api.create_alteration_job(
        {"gown_order_id": order["id"], "estimated_labor_minutes": 60}, SEAMSTRESS), 201)
    validate_success(api.start_fitting_alteration_job(job["id"], SEAMSTRESS), 200)
    validate_success(api.request_adjustment_alteration_job(job["id"], SEAMSTRESS), 200)
    validate_success(api.log_labor_alteration_job(job["id"], {"minutes": 50}, SEAMSTRESS), 200)
    validate_success(api.request_adjustment_alteration_job(job["id"], SEAMSTRESS), 200)
    validate_success(api.log_labor_alteration_job(job["id"], {"minutes": 40}, SEAMSTRESS), 200)

    completed = validate_success(api.complete_alteration_job(job["id"], SEAMSTRESS), 200)
    assert completed["estimated_cost_cents"] == 7200
    assert completed["refitting_count"] == 2
    assert completed["actual_labor_minutes"] == 90
    assert completed["final_cost_cents"] == 12960, (
        f"final_cost_cents should be 12960, got {completed['final_cost_cents']}"
    )


# ─── combinatorial_formula / payment_plan_schedule_nonlinear_three_inputs ────

def test_payment_plan_waterfall_installment_and_total(api):
    """PRD §3.6: "The base installment is the financed amount divided by
    `term_installments`, rounded down to a whole cent." With plan_total 305000,
    deposit 160000, term 3: financed 145000, base floor(145000/3) = 48333.

    Design: Difficulty/combinatorial_formula/payment_plan_schedule_nonlinear_three_inputs
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    create_active_accessory(order["id"], accessory_type="VEIL", price_cents=15000)
    res = api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 3, "deposit_cents": 160000}, CLERK)
    plan = validate_success(res, 201)
    assert plan["plan_total_cents"] == 305000, (
        f"plan_total_cents should be 305000, got {plan['plan_total_cents']}"
    )
    assert plan["installment_cents"] == 48333, (
        f"installment_cents should be 48333, got {plan['installment_cents']}"
    )
    assert plan["balance_due_cents"] == 305000


def test_payment_plan_total_snapshots_quoted_plus_active_accessories(api):
    """PRD §3.6: "On creation the plan snapshots its `plan_total_cents` as the order's
    `quoted_total_cents` plus the sum of `price_cents` across the order's currently
    `ACTIVE` accessory add-ons". Quoted 290000 + active VEIL 15000 = 305000.

    Design: Difficulty/combinatorial_formula/payment_plan_schedule_nonlinear_three_inputs
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    create_active_accessory(order["id"], accessory_type="VEIL", price_cents=15000)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 3, "deposit_cents": 160000}, CLERK), 201)
    assert plan["plan_total_cents"] == 305000


# ─── combinatorial_formula / final_total_rounding_order_pinned_per_line ──────

def test_final_total_round_per_term_then_sum_accessories(api):
    """PRD §3.4: "the two gown percentage terms are each rounded up per term before
    summation, and the accessory sum is added last. This is round-per-term-then-sum,
    not sum-the-raw-amounts-then-round." Base 133333, size 25, rush: size ceil(133333*0.15)
    =20000, rush ceil(133333*0.30)=40000 -> subtotal 193333; +TIARA 5001 +SASH 2999 = 201333.

    Design: Difficulty/combinatorial_formula/final_total_rounding_order_pinned_per_line
    """
    order = create_draft_order(gown_style_code="BESPOKE", ordered_size=25,
                               base_price_cents=133333, standard_lead_days=45, is_rush=True)
    create_active_accessory(order["id"], accessory_type="TIARA", price_cents=5001)
    create_active_accessory(order["id"], accessory_type="SASH", price_cents=2999)
    create_plan(order["id"], term_installments=2, deposit_cents=101000)
    validate_success(api.submit_gown_order(order["id"], CONSULTANT), 200)

    received = validate_success(api.receive_gown_order(order["id"], MANAGER), 200)
    assert received["quoted_total_cents"] == 193333, (
        f"quoted_total_cents should be 193333, got {received['quoted_total_cents']}"
    )
    assert received["final_total_cents"] == 201333, (
        f"final_total_cents should be 201333, got {received['final_total_cents']}"
    )


def test_quoted_subtotal_uses_per_term_ceiling(api):
    """PRD §3.3: "Each of those two percentage terms is rounded up to a whole cent
    independently, before anything is summed. The gown subtotal is then
    `base_price_cents` plus the size upcharge plus the rush surcharge." Base 133333,
    size 25, rush -> 133333 + 20000 + 40000 = 193333 at quote time.

    Design: Difficulty/combinatorial_formula/final_total_rounding_order_pinned_per_line
    """
    res = api.create_gown_order(
        {"gown_style_code": "BESPOKE", "ordered_size": 25, "base_price_cents": 133333,
         "standard_lead_days": 45, "is_rush": True}, CONSULTANT)
    order = validate_success(res, 201)
    assert order["quoted_total_cents"] == 193333


# ─── Corner: calculations ────────────────────────────────────────────────────

def test_size_upcharge_applies_at_floor_boundary(api):
    """PRD §3.3: "A plus-size upcharge applies only when `ordered_size` is at least the
    size-upcharge floor of 20: in that case the upcharge is fifteen percent of
    `base_price_cents`, rounded up to the next whole cent". Size 20 on base 180000:
    180000 + ceil(180000*0.15)=27000 = 207000.

    Design: Corner/calculations/size_upcharge_applies_at_floor_boundary
    """
    res = api.create_gown_order(
        {"gown_style_code": "PLUSFIT", "ordered_size": 20, "base_price_cents": 180000,
         "standard_lead_days": 60}, CONSULTANT)
    order = validate_success(res, 201)
    assert order["quoted_total_cents"] == 207000, (
        f"quoted_total_cents should be 207000, got {order['quoted_total_cents']}"
    )


def test_removed_accessory_excluded_from_final_total(api):
    """PRD §3.4: "`REMOVED` add-ons are excluded." A 5000 SASH removed before receive on a
    base-180000 size-10 non-rush order leaves final_total_cents at 180000.

    Design: Corner/calculations/removed_accessory_excluded_from_final_total
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    acc = create_active_accessory(order["id"], accessory_type="SASH", price_cents=5000)
    removed = validate_success(api.remove_accessory_addon(acc["id"], CONSULTANT), 200)
    assert removed["status"] == "REMOVED"
    create_plan(order["id"], term_installments=2, deposit_cents=90000)
    validate_success(api.submit_gown_order(order["id"], CONSULTANT), 200)

    received = validate_success(api.receive_gown_order(order["id"], MANAGER), 200)
    assert received["final_total_cents"] == 180000, (
        f"final_total_cents should be 180000, got {received['final_total_cents']}"
    )


def test_deposit_coverage_flips_order_to_deposit_paid(api):
    """PRD §3.7: "When the cumulative `amount_paid_cents` reaches the deposit (at least
    `deposit_cents`) but the plan is not yet fully paid ... the plan advances
    `DEPOSIT_DUE -> ACTIVE` and the linked order's `payment_status` advances
    `UNPAID -> DEPOSIT_PAID`." Deposit 90000 on a 180000 plan: paid 90000, balance 90000.

    Design: Corner/calculations/deposit_coverage_flips_order_to_deposit_paid
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    plan = create_plan(order["id"], term_installments=2, deposit_cents=90000)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": plan["version"]}, CLERK), 201)

    fresh_plan = get_plan(plan["id"])
    assert fresh_plan["status"] == "ACTIVE"
    assert fresh_plan["amount_paid_cents"] == 90000
    assert fresh_plan["balance_due_cents"] == 90000
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["payment_status"] == "DEPOSIT_PAID"
