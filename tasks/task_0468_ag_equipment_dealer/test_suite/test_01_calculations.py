"""Monetary calculations: flat-rate labor, floor-plan interest, deal amount due,
lease payment, trade-in appraisal, whole-goods deposit, warranty reimbursement.

Every monetary figure is whole integer cents with round-half-up (PRD §2.8).
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_unit_payload, create_floor_plan_note_payload, create_customer_payload,
    create_trade_in_payload, create_deal_payload, create_work_order_payload,
    create_part_payload, create_part_line_payload, create_whole_goods_order_payload,
    create_warranty_claim_payload,
    create_customer, create_unit, create_part, create_offered_trade_in,
    create_approved_deal, fund_deal, get_unit_version, create_active_floor_plan_note,
    create_in_progress_work_order, setup_submitted_claim, create_confirmed_order,
    create_placed_order, add_part_line,
    TEST_USERS,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]


# ─── Flat-rate labor: estimate vs actual (Difficulty/dual_variant_calc) ──────

def test_labor_charge_uses_actual_hours_at_close(api):
    """PRD §3.6: "Once the work order is `CLOSED`, `labor_charge_cents` is
    recomputed from the technician's `actual_hours`; a job that runs slower than
    book (actual greater than flat) bills more, and an efficient job (actual below
    flat) bills less."

    Design: Difficulty/dual_variant_calc/labor_charge_estimate_vs_actual_on_work_order
    """
    _, _, wo, _, _ = create_in_progress_work_order(
        wo_overrides={"labor_rate_cents": 15000, "flat_rate_hours": 3.5}
    )
    # While IN_PROGRESS the estimate is flat_rate_hours * rate = 3.5 * 15000 = 52500.
    assert wo["labor_charge_cents"] == 52500, "estimate should reflect book hours"
    closed = validate_success(
        api.close_work_order(wo["id"], {"actual_hours": 4.0}, SERVICE), 200
    )
    assert closed["status"] == "CLOSED"
    # Final charge recomputes from actual_hours: 4.0 * 15000 = 60000, distinct from 52500.
    assert closed["labor_charge_cents"] == 60000


def test_labor_charge_estimate_reflects_book_hours_while_in_progress(api):
    """PRD §3.6: "While the work order is `OPEN` or `IN_PROGRESS`,
    `labor_charge_cents` reflects the flat-rate estimate computed from the book
    `flat_rate_hours` and ignores `actual_hours`."

    Design: Difficulty/dual_variant_calc/labor_charge_estimate_vs_actual_on_work_order
    """
    _, _, wo, _, _ = create_in_progress_work_order(
        wo_overrides={"labor_rate_cents": 15000, "flat_rate_hours": 3.5}
    )
    # 3.5 book hours * 15000 = 52500, the estimate observed before close.
    assert wo["status"] == "IN_PROGRESS"
    assert wo["labor_charge_cents"] == 52500


# ─── Floor-plan interest: full principal accrual (Difficulty/dual_variant_calc) ──

def test_floor_plan_interest_full_principal_at_100_days(api):
    """PRD §3.2: "The accrued interest is that outstanding base multiplied by the
    daily rate and multiplied by `days_outstanding`, with the result rounded half
    up to whole cents and stored in `interest_accrued_cents`."

    Design: Difficulty/dual_variant_calc/floor_plan_interest_full_principal_vs_declining_balance
    """
    unit = create_unit(condition="NEW", dealer_cost_cents=30000000, list_price_cents=41000000)
    note = create_active_floor_plan_note(unit["id"], principal_cents=30000000, annual_rate_bps=875)
    get_success_data(api.set_clock({"to_iso8601": "2026-04-11T00:00:00Z"}, ADMIN))
    recomputed = validate_success(api.recompute_floor_plan_note(note["id"], FINANCE), 200)
    # 30000000 * (875/10000/365) * 100 days, round half up = 719178.
    assert recomputed["days_outstanding"] == 100
    assert recomputed["interest_accrued_cents"] == 719178


def test_floor_plan_interest_recomputed_lazily_on_read(api):
    """PRD §2.5: "Retrieving a single floor-plan note recomputes its
    `interest_accrued_cents` and `days_outstanding` against the current clock
    before returning it."

    Design: Difficulty/dual_variant_calc/floor_plan_interest_full_principal_vs_declining_balance
    """
    unit = create_unit(condition="NEW", dealer_cost_cents=30000000, list_price_cents=41000000)
    note = create_active_floor_plan_note(unit["id"], principal_cents=30000000, annual_rate_bps=875)
    get_success_data(api.set_clock({"to_iso8601": "2026-04-11T00:00:00Z"}, ADMIN))
    fetched = validate_success(api.get_floor_plan_note(note["id"], FINANCE), 200)
    assert fetched["days_outstanding"] == 100
    assert fetched["interest_accrued_cents"] == 719178


# ─── Deal amount due: trade-reduced taxable base (Difficulty/combinatorial_formula) ──

def test_deal_amount_due_tax_keyed_on_trade_reduced_base(api):
    """PRD §3.4: "the `tax_cents` is zero if the customer is tax-exempt; otherwise
    it is the taxable base multiplied by the tax rate of 0.0725 (7.25%), rounded
    half up to whole cents — tax is computed on the taxable base after the trade
    reduction, not on the gross price."

    Design: Difficulty/combinatorial_formula/deal_amount_due_circular_tax_keyed_on_trade_reduced_base
    """
    customer = get_success_data(api.create_customer(
        create_customer_payload(name="Tax Buyer", customer_type="RETAIL", tax_exempt=False), FINANCE))
    unit = create_unit(condition="NEW", model_code="5075E", dealer_cost_cents=7000000,
                       list_price_cents=10000000)
    trade = create_offered_trade_in(customer["id"], model_code="5065E", engine_hours=1200,
                                    condition_grade="GOOD", base_value_cents=4000000)
    deal = get_success_data(api.create_deal(create_deal_payload(
        unit["id"], customer["id"], deal_type="SALE", sale_price_cents=10000000,
        tradein_id=trade["id"]), SALES))
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    funded = fund_deal(deal["id"], unit["id"])
    # trade allowance = 4000000 * 0.85 * (1 - 0.12) = 2992000; taxable = 7008000;
    # tax = round(7008000 * 0.0725) = 508080; amount_due = 7516080.
    assert funded["trade_allowance_cents"] == 2992000
    assert funded["tax_cents"] == 508080
    assert funded["amount_due_cents"] == 7516080


def test_deal_amount_due_no_trade_taxes_full_price(api):
    """PRD §3.4: "the `amount_due_cents` is the taxable base plus `tax_cents`."
    PRD §3.4: "the taxable base is the `sale_price_cents` minus the trade
    allowance, floored at zero".

    Design: Difficulty/combinatorial_formula/deal_amount_due_circular_tax_keyed_on_trade_reduced_base
    """
    customer = create_customer(name="No Trade", customer_type="RETAIL")
    unit, _, deal = create_approved_deal(
        unit_overrides={"condition": "NEW", "dealer_cost_cents": 7000000, "list_price_cents": 10000000},
        customer_overrides={"name": "No Trade", "customer_type": "RETAIL"},
        deal_overrides={"deal_type": "SALE", "sale_price_cents": 10000000},
    )
    funded = fund_deal(deal["id"], unit["id"])
    # No trade: taxable base = 10000000; tax = round(10000000 * 0.0725) = 725000; due = 10725000.
    assert funded["trade_allowance_cents"] == 0
    assert funded["tax_cents"] == 725000
    assert funded["amount_due_cents"] == 10725000


# ─── Lease monthly payment: nested rounding pinned (Difficulty/combinatorial_formula) ──

def test_lease_monthly_payment_standard_tier_nested_rounding(api):
    """PRD §3.4: "The `monthly_payment_cents` is the base monthly amount plus the
    rent charge, with a single round-half-up applied to that sum — this is the
    second rounding step."

    Design: Difficulty/combinatorial_formula/lease_monthly_payment_nested_rounding_order_pinned
    """
    customer = get_success_data(api.create_customer(
        create_customer_payload(name="Lessee Co", customer_type="COMMERCIAL_AG",
                                credit_tier="STANDARD"), FINANCE))
    unit = create_unit(condition="NEW", model_code="6R145", dealer_cost_cents=9000000,
                       list_price_cents=12000000)
    deal = get_success_data(api.create_deal(create_deal_payload(
        unit["id"], customer["id"], deal_type="LEASE", sale_price_cents=12000000,
        lease_term_months=60), SALES))
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    funded = fund_deal(deal["id"], unit["id"])
    # residual = round(12000000 * 0.50) = 6000000; cap_cost = 12000000;
    # depreciation = 6000000; base_monthly = 6000000/60 = 100000;
    # rent = (12000000 + 6000000) * 0.0015 = 27000; monthly = round(127000) = 127000.
    assert funded["monthly_payment_cents"] == 127000


def test_lease_funding_moves_unit_to_leased(api):
    """PRD §3.4: "It then moves the unit `RESERVED → SOLD` for a sale or
    `RESERVED → LEASED` for a lease."

    Design: Difficulty/combinatorial_formula/lease_monthly_payment_nested_rounding_order_pinned
    """
    customer = get_success_data(api.create_customer(
        create_customer_payload(name="Lessee Two", customer_type="COMMERCIAL_AG",
                                credit_tier="STANDARD"), FINANCE))
    unit = create_unit(condition="NEW", model_code="6R145", dealer_cost_cents=9000000,
                       list_price_cents=12000000)
    deal = get_success_data(api.create_deal(create_deal_payload(
        unit["id"], customer["id"], deal_type="LEASE", sale_price_cents=12000000,
        lease_term_months=60), SALES))
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    fund_deal(deal["id"], unit["id"])
    unit_after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert unit_after["status"] == "LEASED"


# ─── Trade-in appraisal (Corner/calculations) ────────────────────────────────

def test_trade_in_hour_penalty_capped_at_40pct(api):
    """PRD §3.3: "The hours penalty is one percent of base for each full 100 engine
    hours, capped at 40 percent: take the floor of `engine_hours` divided by 100,
    multiply by 0.01, and use the smaller of that figure and 0.40 as the penalty
    fraction."

    Design: Corner/calculations/trade_in_appraisal_hour_penalty_capped_at_40pct
    """
    customer = get_success_data(api.create_customer(
        create_customer_payload(name="Cap Cust", customer_type="RETAIL"), SALES))
    ti = validate_success(api.create_trade_in(create_trade_in_payload(
        customer["id"], model_code="4720", engine_hours=6000, condition_grade="POOR",
        base_value_cents=1000000), SALES), 201)
    # 6000 hrs would be 60% penalty but capped at 40%: 1000000 * 0.40 * (1 - 0.40) = 240000.
    assert ti["appraised_value_cents"] == 240000


# ─── Whole-goods deposit & net price (Corner/calculations) ───────────────────

def test_whole_goods_deposit_floor_beats_percentage(api):
    """PRD §3.8: "The required `deposit_cents` is the larger of the percentage
    deposit and the floor deposit."

    Design: Corner/calculations/whole_goods_deposit_floor_beats_percentage
    """
    customer, order = create_placed_order(
        customer_overrides={"name": "Floor Cust", "customer_type": "RETAIL"},
        order_overrides={"model_code": "Z930M", "season_program": "LATE", "quantity": 1,
                         "unit_msrp_cents": 400000},
    )
    # net = round(400000 * 1.00) = 400000.
    assert order["net_price_cents"] == 400000
    confirmed = validate_success(api.confirm_whole_goods_order(order["id"], SALES), 200)
    # pct deposit = round(400000 * 0.10) = 40000; floor = 50000 * 1 = 50000; max = 50000.
    assert confirmed["deposit_cents"] == 50000


def test_whole_goods_early_order_discount_and_pct_deposit(api):
    """PRD §3.8: "The `net_price_cents` is the `unit_msrp_cents` multiplied by one
    minus the discount fraction, rounded half up — this per-unit net price is
    rounded first."

    Design: Corner/calculations/whole_goods_early_order_discount_and_pct_deposit
    """
    customer, order = create_placed_order(
        customer_overrides={"name": "Early Cust", "customer_type": "COMMERCIAL_AG"},
        order_overrides={"model_code": "9RX640", "season_program": "EARLY_ORDER", "quantity": 2,
                         "unit_msrp_cents": 20000000},
    )
    # net = round(20000000 * 0.88) = 17600000.
    assert order["net_price_cents"] == 17600000
    confirmed = validate_success(api.confirm_whole_goods_order(order["id"], SALES), 200)
    # total = 35200000; pct = round(35200000 * 0.10) = 3520000 (> floor 100000).
    assert confirmed["deposit_cents"] == 3520000


def test_deal_amount_due_tax_exempt_customer_zero_tax(api):
    """PRD §3.4: "the `tax_cents` is zero if the customer is tax-exempt".

    Design: Corner/calculations/deal_amount_due_tax_exempt_customer_zero_tax
    """
    customer = get_success_data(api.create_customer(
        create_customer_payload(name="Exempt Farm", customer_type="COMMERCIAL_AG",
                                tax_exempt=True), FINANCE))
    unit = create_unit(condition="NEW", model_code="8R310", dealer_cost_cents=7500000,
                       list_price_cents=10000000)
    deal = get_success_data(api.create_deal(create_deal_payload(
        unit["id"], customer["id"], deal_type="SALE", sale_price_cents=10000000), SALES))
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    funded = fund_deal(deal["id"], unit["id"])
    assert funded["tax_cents"] == 0
    assert funded["amount_due_cents"] == 10000000


# ─── Warranty reimbursement (Corner/calculations) ────────────────────────────

def test_warranty_pip_reimburses_full_claimed(api):
    """PRD §3.7: "a `PIP` or `RECALL` claim is manufacturer-funded and reimburses
    100 percent of `claimed_cents`, so its full amount equals `claimed_cents`".

    Design: Corner/calculations/warranty_pip_reimburses_full_claimed
    """
    _, _, claim, wo = setup_submitted_claim(claim_type="PIP", campaign_code="PIP-7")
    assert wo["total_charge_cents"] == 110000
    assert claim["claimed_cents"] == 110000
    adjudicated = validate_success(
        api.adjudicate_warranty_claim(claim["id"], {"decision": "FULL"}, ADMIN), 200)
    assert adjudicated["status"] == "APPROVED"
    assert adjudicated["approved_cents"] == 110000


def test_warranty_plain_partial_applies_cap_then_half(api):
    """PRD §3.7: "a plain `WARRANTY` claim is subject to a labor cap and its full
    amount is `claimed_cents` multiplied by 0.90 (90 percent), rounded half up.
    From that full amount the decision selects the approved figure: ... a `PARTIAL`
    decision approves the full amount multiplied by the partial factor of 0.50,
    rounded half up".

    Design: Corner/calculations/warranty_plain_partial_applies_cap_then_half
    """
    _, _, claim, _ = setup_submitted_claim(claim_type="WARRANTY")
    assert claim["claimed_cents"] == 110000
    adjudicated = validate_success(
        api.adjudicate_warranty_claim(claim["id"], {"decision": "PARTIAL"}, ADMIN), 200)
    # full = round(110000 * 0.90) = 99000; partial = round(99000 * 0.50) = 49500.
    assert adjudicated["approved_cents"] == 49500
    assert adjudicated["status"] == "PARTIAL"


def test_part_line_extended_snapshot_and_wo_parts_charge(api):
    """PRD §3.6: "On creation the line snapshots the part's current price into
    `unit_price_cents` and sets `extended_cents` to the `quantity` multiplied by
    that snapshot price".

    Design: Corner/calculations/part_line_extended_snapshot_and_wo_parts_charge
    """
    # Build an OPEN work order and a priced part, then add the line.
    customer = create_customer(name="PL Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5085E", engine_hours=800)
    part = create_part(sku="ALT-3", description="alternator", category="MECHANICAL",
                       unit_price_cents=25000, on_hand_qty=5)
    wo = get_success_data(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="charging", labor_rate_cents=14000,
        flat_rate_hours=2.0), SERVICE))
    pl = validate_success(api.add_part_line(
        wo["id"], create_part_line_payload(part["id"], 2), PARTS), 201)
    assert pl["unit_price_cents"] == 25000
    assert pl["extended_cents"] == 50000
