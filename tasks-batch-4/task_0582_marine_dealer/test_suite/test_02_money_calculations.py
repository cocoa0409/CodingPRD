"""Monetary calculations: deal financials, repair-order estimate/final, per-line rounding."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures,
    create_deal_payload,
)

MANAGER = TEST_USERS["manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]


def test_deal_tax_base_and_trade_equity(api):
    """PRD §3.3: "The `trade_equity_cents` is the `trade_allowance_cents` minus the
    `trade_lien_payoff_cents`, and may be negative when the trade is underwater." PRD
    §3.3: "the sale price minus the greater of zero and `trade_allowance_cents`, with
    the whole result floored at zero — and `tax_cents` is that base multiplied by
    `tax_rate_bps`, divided by 10000, rounded half up."

    Design: Difficulty/combinatorial_formula/deal_amount_due_nested_max_and_tradein
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH")
    payload = create_deal_payload(
        unit["id"], sale_price_cents=5000000, financing_type="RETAIL_FINANCE",
        tax_rate_bps=725, doc_fee_cents=39900, down_payment_cents=1000000,
        trade_allowance_cents=1200000, trade_lien_payoff_cents=400000,
    )
    data = validate_success(api.create_deal(payload, SALES), expected_status=201)
    assert data["trade_equity_cents"] == 800000, \
        f"Expected trade_equity 800000, got {data['trade_equity_cents']}"
    assert data["tax_cents"] == 275500, f"Expected tax 275500, got {data['tax_cents']}"


def test_deal_amount_due_combines_all_terms(api):
    """PRD §3.3: "the net cash the buyer owes at funding, `amount_due_cents`, is the
    `sale_price_cents` plus `tax_cents` plus `doc_fee_cents`, less the
    `down_payment_cents`, less the `trade_equity_cents`."

    Design: Difficulty/combinatorial_formula/deal_amount_due_nested_max_and_tradein
    """
    unit = fixtures.create_available_unit(acquisition_type="CASH")
    payload = create_deal_payload(
        unit["id"], sale_price_cents=5000000, financing_type="RETAIL_FINANCE",
        tax_rate_bps=725, doc_fee_cents=39900, down_payment_cents=1000000,
        trade_allowance_cents=1200000, trade_lien_payoff_cents=400000,
    )
    data = validate_success(api.create_deal(payload, SALES), expected_status=201)
    assert data["amount_due_cents"] == 3515400, \
        f"Expected amount_due 3515400, got {data['amount_due_cents']}"


def test_repair_order_estimate_from_estimated_hours(api):
    """PRD §3.5: "for a `DIAGNOSTIC` or `CUSTOM` order the pre-tax base is
    `estimated_hours` multiplied by `labor_rate_cents_per_hour`, rounded half up. In
    either case the `estimate_total_cents` is that base plus the tax on the base — the
    base multiplied by `tax_rate_bps`, divided by 10000, rounded half up."

    Design: Difficulty/dual_variant_calc/repair_order_estimate_vs_final
    """
    _unit, _bay, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 12000,
                      "tax_rate_bps": 725, "estimated_hours": 4.0},
    )
    assert ro["estimate_total_cents"] == 51480, \
        f"Expected estimate 51480, got {ro['estimate_total_cents']}"


def test_repair_order_final_total_from_actual_lines(api):
    """PRD §3.6: "Those already-rounded line extensions are then summed into a subtotal
    with no further rounding, and the `final_total_cents` is that subtotal plus the tax
    on it — the subtotal multiplied by `tax_rate_bps`, divided by 10000, rounded half up."

    Design: Difficulty/dual_variant_calc/repair_order_estimate_vs_final
    """
    part = fixtures.create_part(on_hand_qty=10, list_price_cents=4599)
    _unit, _bay, ro_done, _lines = fixtures.create_completed_ro(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 12000,
                      "tax_rate_bps": 725, "estimated_hours": 4.0},
        lines=[
            ("LABOR", {"hours": 2.5, "unit_price_cents": 12000}),
            ("PART", {"part_id": part["id"], "quantity": 3, "unit_price_cents": 4599}),
            ("LABOR", {"hours": 1.25, "unit_price_cents": 12000}),
        ],
    )
    assert ro_done["final_total_cents"] == 63060, \
        f"Expected final 63060, got {ro_done['final_total_cents']}"


def test_service_line_extended_cents_rounded_per_line(api):
    """PRD §3.6: "a `LABOR` line's `extended_cents` is its `hours` multiplied by its
    effective price, rounded half up; a `PART` line's `extended_cents` is its `quantity`
    multiplied by its effective price, rounded half up."

    Design: Difficulty/combinatorial_formula/repair_order_final_round_per_line_then_sum
    """
    _unit, _bay, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 10033,
                      "tax_rate_bps": 0, "estimated_hours": 4.0},
    )
    line1 = fixtures.add_service_line(ro["id"], "LABOR", hours=1.5, unit_price_cents=10033)
    line2 = fixtures.add_service_line(ro["id"], "LABOR", hours=2.5, unit_price_cents=10033)
    l1 = validate_success(api.get_service_line(line1["id"], SERVICE))
    l2 = validate_success(api.get_service_line(line2["id"], SERVICE))
    assert l1["extended_cents"] == 15050, f"Expected 15050, got {l1['extended_cents']}"
    assert l2["extended_cents"] == 25083, f"Expected 25083, got {l2['extended_cents']}"


def test_repair_order_final_rounds_each_line_before_summation(api):
    """PRD §3.6: "The per-line rounding is fixed before summation deliberately, so the
    final total can differ from taxing a single combined figure." PRD §3.6: "Those
    already-rounded line extensions are then summed into a subtotal with no further
    rounding, and the `final_total_cents` is that subtotal plus the tax on it".

    Design: Difficulty/combinatorial_formula/repair_order_final_round_per_line_then_sum
    """
    _unit, _bay, ro_done, _lines = fixtures.create_completed_ro(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 10033,
                      "tax_rate_bps": 0, "estimated_hours": 4.0},
        lines=[
            ("LABOR", {"hours": 1.5, "unit_price_cents": 10033}),
            ("LABOR", {"hours": 2.5, "unit_price_cents": 10033}),
        ],
    )
    assert ro_done["final_total_cents"] == 40133, \
        f"Expected final 40133 (per-line rounded), got {ro_done['final_total_cents']}"
