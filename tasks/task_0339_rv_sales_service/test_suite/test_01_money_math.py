"""Deal and service-order money math: trade equity variants, pinned tax/finance
evaluation order, round-then-sum labor, monthly payment band, storage charge,
consignor waterfall, and cash amount-due.

Covers the dual_variant_calc and combinatorial_formula difficulty rules plus the
calculations corner instances.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    setup_held_deal,
    setup_dealership_customer_unit,
    create_deal_on_unit,
    setup_warranty_so_in_progress,
    setup_nonwarranty_so_in_progress,
    setup_finance_requested_deal,
    setup_active_storage_slot,
    create_customer,
    create_unit,
    appraise_trade_payload,
    create_pdi_inspection_payload,
)

SALES = TEST_USERS["sales_agent_headers"]
MGR = TEST_USERS["dealer_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / trade_equity_applied_vs_dealer_book
# ===========================================================================
def test_equity_summary_applied_credit_excludes_recon(api):
    """PRD §3.3: "the buyer's credit, stored as `net_trade_equity_cents`, equals
    the `trade_allowance_cents` minus the `trade_payoff_cents`, and this figure
    may be negative; reconditioning cost is the dealer's risk and is deliberately
    **not** subtracted from the buyer's credit."

    Allowance 2000000 - payoff 500000 = 1500000 applied credit (recon 300000 not netted).

    Design: Difficulty/dual_variant_calc/trade_equity_applied_vs_dealer_book
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        unit_overrides={"list_price_cents": 8000000},
        sale_price_cents=8000000,
        down_payment_cents=0,
    )
    get_success_data(
        api_client.appraise_trade(
            deal["id"],
            appraise_trade_payload(
                model_year=2018, class_type="TRAVEL_TRAILER", list_price_cents=2500000,
                trade_allowance_cents=2000000, trade_payoff_cents=500000,
                trade_recon_cost_cents=300000,
            ),
            SALES,
        )
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    summary = validate_success(api.get_equity_summary(deal["id"], SALES))
    assert summary["net_trade_equity_cents"] == 1500000, summary["net_trade_equity_cents"]


def test_equity_summary_dealer_book_subtracts_recon(api):
    """PRD §3.3: "the deal also records `dealer_book_equity_cents`, the dealer's
    margin view of the same trade, which equals the `trade_allowance_cents` minus
    the `trade_payoff_cents` minus the `trade_recon_cost_cents`; with no trade it
    too is zero. The two equity figures differ by exactly the reconditioning cost."

    Dealer-book = 2000000 - 500000 - 300000 = 1200000; applied 1500000 diverges by recon 300000.

    Design: Difficulty/dual_variant_calc/trade_equity_applied_vs_dealer_book
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        unit_overrides={"list_price_cents": 8000000},
        sale_price_cents=8000000,
        down_payment_cents=0,
    )
    get_success_data(
        api_client.appraise_trade(
            deal["id"],
            appraise_trade_payload(
                model_year=2018, class_type="TRAVEL_TRAILER", list_price_cents=2500000,
                trade_allowance_cents=2000000, trade_payoff_cents=500000,
                trade_recon_cost_cents=300000,
            ),
            SALES,
        )
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    summary = validate_success(api.get_equity_summary(deal["id"], SALES))
    assert summary["dealer_book_equity_cents"] == 1200000, summary["dealer_book_equity_cents"]
    assert summary["net_trade_equity_cents"] - summary["dealer_book_equity_cents"] == 300000


# ===========================================================================
# Difficulty: dual_variant_calc / service_total_warranty_covered_vs_owed
# ===========================================================================
def test_warranty_order_covered_is_full_gross(api):
    """PRD §3.7: "For a warranty order, the plan's remaining headroom is its
    `coverage_cap_cents` minus its `consumed_cents`; the coverable portion is the
    gross minus the plan's `deductible_cents`, floored at zero; `covered_cents` is
    the smaller of that coverable portion and the remaining headroom".

    Gross = labor round(2.5*12000)=30000 + part 270000 = 300000; cap 300000 ded 0 ->
    covered 300000.

    Design: Difficulty/dual_variant_calc/service_total_warranty_covered_vs_owed
    """
    dealer, customer, unit, plan, part, so = setup_warranty_so_in_progress(
        plan_cap_cents=300000, deductible_cents=0,
        labor_hours=2.5, labor_rate_cents=12000,
        part_price_cents=270000, part_qty_on_hand=5, reserve_qty=1,
    )
    completed = validate_success(api.complete_service_order(so["id"], SVC))
    assert completed["covered_cents"] == 300000, completed["covered_cents"]


def test_warranty_order_customer_owed_is_zero(api):
    """PRD §3.7: "and `total_cents` is the gross minus `covered_cents`."

    Gross 300000 fully covered -> total_cents 0; the plan reaching its cap exhausts it.

    Design: Difficulty/dual_variant_calc/service_total_warranty_covered_vs_owed
    """
    dealer, customer, unit, plan, part, so = setup_warranty_so_in_progress(
        plan_cap_cents=300000, deductible_cents=0,
        labor_hours=2.5, labor_rate_cents=12000,
        part_price_cents=270000, part_qty_on_hand=5, reserve_qty=1,
    )
    completed = validate_success(api.complete_service_order(so["id"], SVC))
    assert completed["total_cents"] == 0, completed["total_cents"]
    plan_after = validate_success(api.get_warranty_plan(plan["id"], SVC))
    assert plan_after["status"] == "EXHAUSTED", plan_after["status"]


# ===========================================================================
# Difficulty: combinatorial_formula / amount_financed_pinned_evaluation_order
# ===========================================================================
def test_quote_tax_uses_taxable_base_after_trade_credit(api):
    """PRD §3.3: "the taxable base is the `sale_price_cents` reduced by the applied
    `net_trade_equity_cents`, floored at zero so it never goes negative. The
    `tax_cents` is that taxable base multiplied by the `sales_tax_rate_bps` and
    divided by ten thousand, rounded half up to whole cents — and the
    documentation fee is never taxed."

    Taxable base = 8000000 - 1500000 = 6500000; tax = round_half_up(6500000*725/10000) = 471250.

    Design: Difficulty/combinatorial_formula/amount_financed_pinned_evaluation_order
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        unit_overrides={"list_price_cents": 8000000},
        sale_price_cents=8000000,
        down_payment_cents=0,
    )
    get_success_data(
        api_client.appraise_trade(
            deal["id"],
            appraise_trade_payload(
                model_year=2017, class_type="FIFTH_WHEEL", list_price_cents=2000000,
                trade_allowance_cents=2000000, trade_payoff_cents=500000,
                trade_recon_cost_cents=300000,
            ),
            SALES,
        )
    )
    quoted = validate_success(api.quote_deal(deal["id"], SALES))
    assert quoted["net_trade_equity_cents"] == 1500000
    assert quoted["tax_cents"] == 471250, quoted["tax_cents"]


def test_quote_amount_financed_pins_full_evaluation_chain(api):
    """PRD §3.3: "the `amount_financed_cents` is the gross amount due reduced by
    the applied `net_trade_equity_cents` and by the `down_payment_cents`, floored
    at zero."
    PRD §3.3: "The gross amount due is the `sale_price_cents` plus the snapshotted
    `doc_fee_cents` plus the `tax_cents`."

    gross = 8000000 + 29900 + 471250 = 8501150; financed = 8501150 - 1500000 - 0 = 7001150.

    Design: Difficulty/combinatorial_formula/amount_financed_pinned_evaluation_order
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        unit_overrides={"list_price_cents": 8000000},
        sale_price_cents=8000000,
        down_payment_cents=0,
    )
    get_success_data(
        api_client.appraise_trade(
            deal["id"],
            appraise_trade_payload(
                model_year=2017, class_type="FIFTH_WHEEL", list_price_cents=2000000,
                trade_allowance_cents=2000000, trade_payoff_cents=500000,
                trade_recon_cost_cents=300000,
            ),
            SALES,
        )
    )
    quoted = validate_success(api.quote_deal(deal["id"], SALES))
    assert quoted["amount_financed_cents"] == 7001150, quoted["amount_financed_cents"]


# ===========================================================================
# Difficulty: combinatorial_formula / service_order_total_round_then_sum_labor
# ===========================================================================
def test_parts_subtotal_is_exact_integer_sum(api):
    """PRD §3.7: "The parts portion, stored as `parts_subtotal_cents`, is the
    exact-integer sum over the order's `RESERVED` reservations of each
    reservation's `quantity` times its snapshotted `unit_price_cents`."

    2 * 45050 = 90100 exact parts subtotal.

    Design: Difficulty/combinatorial_formula/service_order_total_round_then_sum_labor
    """
    dealer, customer, unit, part, so = setup_nonwarranty_so_in_progress(
        labor_hours=2.345, labor_rate_cents=10000,
        part_price_cents=45050, part_qty_on_hand=5, reserve_qty=2,
    )
    completed = validate_success(api.complete_service_order(so["id"], SVC))
    assert completed["parts_subtotal_cents"] == 90100, completed["parts_subtotal_cents"]


def test_service_total_rounds_labor_before_summing_parts(api):
    """PRD §3.7: "Labor cost is the `labor_hours` multiplied by the
    `labor_rate_cents`, rounded half up to whole cents — and this labor figure is
    rounded first, before anything is summed."
    PRD §3.7: "The gross is the rounded labor plus the exact parts subtotal."

    labor round_half_up(2.345*10000)=23450, parts 90100 -> total 113550 (round-then-sum).

    Design: Difficulty/combinatorial_formula/service_order_total_round_then_sum_labor
    """
    dealer, customer, unit, part, so = setup_nonwarranty_so_in_progress(
        labor_hours=2.345, labor_rate_cents=10000,
        part_price_cents=45050, part_qty_on_hand=5, reserve_qty=2,
    )
    completed = validate_success(api.complete_service_order(so["id"], SVC))
    assert completed["total_cents"] == 113550, completed["total_cents"]


# ===========================================================================
# Corner: calculations / storage_charge_winterized_ceil_days
# ===========================================================================
def test_storage_charge_ceil_days_plus_winterize_fee(api):
    """PRD §3.10: "the billed day count is the elapsed seconds divided by the
    number of seconds in a day and rounded up to the next whole day, with a
    minimum of one day so that even a same-day release bills a full day. The base
    charge is that day count multiplied by the `daily_rate_cents`, and when the
    slot is `winterized` a flat winterization fee of 25000 cents is added on top."

    start 06-01, release 06-04T12:00 = 3.5 days -> ceil 4; 4*5000 + 25000 = 45000.

    Design: Corner/calculations/storage_charge_winterized_ceil_days
    """
    dealer, customer, unit, slot = setup_active_storage_slot(
        start_utc="2026-06-01T00:00:00.000Z", end_utc="2026-06-30T00:00:00.000Z",
        daily_rate_cents=5000, winterized=True,
    )
    released = validate_success(
        api.release_storage_slot(slot["id"], {"released_on_utc": "2026-06-04T12:00:00.000Z"}, SVC)
    )
    assert released["billed_cents"] == 45000, released["billed_cents"]
    assert released["status"] == "RELEASED"


# ===========================================================================
# Corner: calculations / consignor_proceeds_floor_breach_dealer_absorbs
# ===========================================================================
def test_consignment_delivery_honors_floor_when_breached(api):
    """PRD §3.6: "if the consignor's net would fall below the unit's
    `consignment_floor_cents`, the consignor's net is raised to exactly the floor
    and the commission is recomputed as the `sale_price_cents` minus the floor — a
    figure that may be negative, in which case the dealer absorbs the shortfall."

    Sale 8000000, fee 1000bps -> commission 800000, net 7200000 < floor 7500000, so
    net raised to floor; delivery succeeds and the unit becomes SOLD.

    Design: Corner/calculations/consignor_proceeds_floor_breach_dealer_absorbs
    """
    dealer = get_success_data(
        api_client.create_dealership(
            {"name": "Cnsg RV", "state_code": "TX", "doc_fee_cents": 0, "sales_tax_rate_bps": 0}, MGR
        )
    )
    consignor = create_customer(dealer["id"])
    buyer = create_customer(dealer["id"])
    unit = create_unit(
        dealer["id"], class_type="CLASS_A", acquisition="CONSIGNMENT",
        consignor_customer_id=consignor["id"], list_price_cents=8500000,
        consignment_floor_cents=7500000, consignment_fee_bps=1000,
    )
    deal = create_deal_on_unit(dealer, buyer, unit, 8000000)
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.start_pdi(deal["id"], SALES))
    get_success_data(
        api_client.create_pdi_inspection(
            create_pdi_inspection_payload(dealer["id"], deal["id"], 0), SVC
        )
    )
    delivered = validate_success(api.deliver_deal(deal["id"], SALES))
    assert delivered["sale_status"] == "DELIVERED", delivered["sale_status"]
    unit_after = validate_success(api.get_unit(unit["id"], SALES))
    assert unit_after["status"] == "SOLD", unit_after["status"]


# ===========================================================================
# Corner: calculations / monthly_payment_prime_band_selection
# ===========================================================================
def test_monthly_payment_prime_band(api):
    """PRD §3.4: "the approval selects the APR for the customer's credit tier — 599
    basis points for `PRIME`, 899 basis points for `STANDARD`, and 1499 basis
    points for `SUBPRIME` — and records it as `apr_bps`, computes the amortized
    `monthly_payment_cents`".

    PRIME 599bps, P=6000000, n=60 -> monthly 115969.

    Design: Corner/calculations/monthly_payment_prime_band_selection
    """
    dealer, customer, unit, deal_id = setup_finance_requested_deal(
        credit_tier="PRIME", list_price_cents=8000000, sale_price_cents=6000000,
        term_months=60, down_payment_cents=0,
    )
    approved = validate_success(
        api.finance_decision(deal_id, {"decision": "APPROVE"}, MGR)
    )
    assert approved["apr_bps"] == 599, approved["apr_bps"]
    assert approved["monthly_payment_cents"] == 115969, approved["monthly_payment_cents"]


# ===========================================================================
# Corner: calculations / cash_deal_amount_due_no_trade
# ===========================================================================
def test_cash_deal_amount_due_no_trade(api):
    """PRD §3.3: "the `amount_financed_cents` is the gross amount due reduced by
    the applied `net_trade_equity_cents` and by the `down_payment_cents`, floored
    at zero."
    PRD §3.3: "Quoting advances `sale_status` from `DRAFT` to `QUOTED`, recomputes
    the deal's money fields, and — when no `term_months` was supplied so the deal
    is a cash purchase — moves `finance_status` from `NONE` to `CASH`."

    Sale 8000000, doc 29900, tax round_half_up(8000000*725/10000)=580000, gross
    8609900, down 1000000 -> financed 7609900; finance CASH.

    Design: Corner/calculations/cash_deal_amount_due_no_trade
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        unit_overrides={"list_price_cents": 8500000},
        sale_price_cents=8000000,
        down_payment_cents=1000000,
    )
    quoted = validate_success(api.quote_deal(deal["id"], SALES))
    assert quoted["tax_cents"] == 580000, quoted["tax_cents"]
    assert quoted["amount_financed_cents"] == 7609900, quoted["amount_financed_cents"]
    assert quoted["finance_status"] == "CASH", quoted["finance_status"]
