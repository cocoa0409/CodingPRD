"""The five-step pricing sequence and the weighbridge arithmetic: which value picks the
volume tier, which month's quote survives, and which weights the sample averages use.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    declare_fiber_grade, publish_quote, register_supplier, create_draft_po,
    create_confirmed_po, record_receipt, sublot,
)

BUYER = TEST_USERS["buyer_headers"]

OCC_11 = {"grade_code": "OCC_11", "index_symbol": "PPI_OCC",
          "max_contamination_pct": 3.00, "max_moisture_pct": 12.00,
          "nominal_yield_pct": 88.00, "deink_required": False, "rank_order": 1}


def _priced_order(index_symbol, quote_month, quoted_price, freight_per_ton,
                  contracted_tons, delta, grade_code="OCC_11", **po_overrides):
    """Declare a grade, publish one quote, then price a fresh draft order."""
    declare_fiber_grade(grade_code=grade_code, index_symbol=index_symbol,
                        rank_order=1)
    publish_quote(index_symbol=index_symbol, effective_month=quote_month,
                  published_price_per_ton=quoted_price)
    supplier = register_supplier(name="Delta Fiber Recovery",
                                 freight_per_ton=freight_per_ton)
    po = create_draft_po(supplier["id"], grade_code,
                         contracted_tons=contracted_tons,
                         negotiated_delta_per_ton=delta, **po_overrides)
    return api_client.price_purchase_order(
        po["id"], {"expected_purchase_order_version": po["version"]}, BUYER)


def _confirmed_occ_order():
    declare_fiber_grade(**OCC_11)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             index_basis="CURRENT_MONTH", priced_for_month="2026-08")
    return supplier, po


def test_the_tier_is_read_off_the_provisional_value_the_final_total_crosses_alone():
    """PRD §3.1: "Third, the **volume discount** tier is selected from that provisional
    extended value alone: a provisional value strictly below 100000.00 United States
    dollars earns a discount of exactly 0.000, a value of 100000.00 or more but strictly
    below 250000.00 earns exactly 0.015, and a value of 250000.00 or more earns exactly
    0.030; both tier boundaries are inclusive at the lower edge."
    PRD §3.1: "The discount tier is chosen from the provisional extended value and is
    **never** re-derived from the final `extended_contract_value`, even when adding freight
    and the fuel surcharge pushes the final figure across the 100000.00 or 250000.00
    boundaries."

    Design: Corner/calculations/volume_tier_is_read_off_provisional_extended_even_when_final_value_crosses_the_ceiling
    """
    priced = validate_success(_priced_order("PPI_OCC", "2026-08", 180.00, 12.50,
                                            530.00, 5.00))

    assert priced["status"] == "PRICED"
    assert priced["fuel_surcharge_per_ton"] == pytest.approx(2.31, abs=1e-6)
    assert priced["quoted_unit_price_per_ton"] == pytest.approx(199.81, abs=1e-6)
    assert priced["extended_contract_value"] == pytest.approx(105899.30, abs=1e-6)
    assert priced["index_quote_month_used"] == "2026-08"
    assert priced["pricing_revision_count"] == 0


def test_a_provisional_value_landing_exactly_on_the_ceiling_earns_the_discount():
    """PRD §3.1: "Second, a **provisional extended value** is computed as the base price
    multiplied by `contracted_tons`, rounded half up to two decimal places; freight and
    fuel surcharge are deliberately excluded from this figure."
    PRD §3.1: "Third, the **volume discount** tier is selected from that provisional
    extended value alone: a provisional value strictly below 100000.00 United States
    dollars earns a discount of exactly 0.000, a value of 100000.00 or more but strictly
    below 250000.00 earns exactly 0.015, and a value of 250000.00 or more earns exactly
    0.030; both tier boundaries are inclusive at the lower edge."

    Design: Corner/calculations/provisional_extended_exactly_at_tier1_ceiling_takes_the_1_5_percent_discount
    """
    priced = validate_success(_priced_order("PPI_OCC", "2026-08", 195.00, 12.50,
                                            500.00, 5.00))

    assert priced["quoted_unit_price_per_ton"] == pytest.approx(211.81, abs=1e-6)
    assert priced["extended_contract_value"] == pytest.approx(105905.00, abs=1e-6)
    assert priced["fuel_surcharge_per_ton"] == pytest.approx(2.31, abs=1e-6)


def test_a_prior_month_order_prices_off_the_surviving_quote_of_the_month_before():
    """PRD §3.1: "The target month is the order's `priced_for_month` when `index_basis` is
    `CURRENT_MONTH`, and the calendar month immediately preceding `priced_for_month` when
    `index_basis` is `PRIOR_MONTH`."
    PRD §3.1: "Quotes are append-only: publishing a second quote for the same symbol and
    month does not edit the first, it **supersedes** it."
    PRD §3.1: "Exactly one non-superseded quote therefore survives per symbol and month,
    and that is the row pricing resolves against."

    Design: Corner/calculations/prior_month_basis_resolves_the_surviving_quote_for_the_preceding_month
    """
    declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                        max_contamination_pct=1.50, max_moisture_pct=10.00,
                        nominal_yield_pct=72.00, deink_required=True, rank_order=2)
    stale = publish_quote(index_symbol="PPI_DLK", effective_month="2026-07",
                          published_price_per_ton=300.00)
    publish_quote(index_symbol="PPI_DLK", effective_month="2026-07",
                  published_price_per_ton=260.00)
    publish_quote(index_symbol="PPI_DLK", effective_month="2026-08",
                  published_price_per_ton=400.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=20.00)
    po = create_draft_po(supplier["id"], "DLK_37", contracted_tons=100.00,
                         index_basis="PRIOR_MONTH", priced_for_month="2026-08",
                         negotiated_delta_per_ton=-10.00)

    priced = validate_success(api_client.price_purchase_order(
        po["id"], {"expected_purchase_order_version": po["version"]}, BUYER))
    assert priced["index_quote_month_used"] == "2026-07"
    assert priced["fuel_surcharge_per_ton"] == pytest.approx(3.70, abs=1e-6)
    assert priced["quoted_unit_price_per_ton"] == pytest.approx(273.70, abs=1e-6)
    assert priced["extended_contract_value"] == pytest.approx(27370.00, abs=1e-6)

    superseded = api_client.list_market_index_quotes(
        BUYER, {"index_symbol": "PPI_DLK", "effective_month": "2026-07",
                "superseded": True}).json()
    assert superseded["meta"]["total_count"] == 1
    assert superseded["data"][0]["id"] == stale["id"]
    assert superseded["data"][0]["published_price_per_ton"] == \
        pytest.approx(300.00, abs=1e-6)


def test_a_half_cent_fuel_surcharge_rounds_upward():
    """PRD §3.1: "Fourth, the **fuel surcharge** is derived from the supplier's contracted
    `freight_per_ton` multiplied by a fuel surcharge rate of 0.185, rounded half up to two
    decimal places, and stored as `fuel_surcharge_per_ton`."
    PRD §3.1: "Fifth, the `quoted_unit_price_per_ton` is the base price multiplied by one
    minus the selected discount, plus the supplier's `freight_per_ton`, plus the
    `fuel_surcharge_per_ton` just computed, the whole rounded half up to two decimal
    places; and `extended_contract_value` is that unit price multiplied by
    `contracted_tons`, rounded half up to two decimal places."

    Design: Corner/calculations/fuel_surcharge_rounds_a_half_cent_upward_at_the_declared_rate
    """
    priced = validate_success(_priced_order("PPI_SOP", "2026-08", 100.00, 17.00,
                                            10.00, 0.00, grade_code="SOP_37"))

    assert priced["fuel_surcharge_per_ton"] == pytest.approx(3.15, abs=1e-6)
    assert priced["quoted_unit_price_per_ton"] == pytest.approx(120.15, abs=1e-6)
    assert priced["extended_contract_value"] == pytest.approx(1201.50, abs=1e-6)


def test_three_sublots_rounded_one_at_a_time_move_the_net_tonnage_by_a_cent():
    """PRD §3.2: "Its **deduction** is that wet tonnage multiplied by the moisture excess
    and divided by 100, rounded half up to three decimal places, and its **dry tonnage** is
    the wet tonnage minus that deduction, again rounded half up to three decimal places."
    PRD §3.2: "This per-sublot-then-sum order is pinned: summing raw unrounded deductions
    and rounding once at the end changes `net_tons` in the third decimal for multi-sublot
    trucks, and that alternative is not used."

    Design: Corner/calculations/net_tons_rounds_each_sublot_before_summing_which_moves_the_cent
    """
    supplier, po = _confirmed_occ_order()

    response = api_client.create_receipt(po["id"], {
        "truck_reference": "TRK-ROUND-1",
        "sublots": [sublot(1, 12.210, 2.000, 15.00, 2.00),
                    sublot(2, 9.210, 2.000, 15.00, 1.00),
                    sublot(3, 8.899, 2.000, 13.77, 3.00)]},
        TEST_USERS["lab_sampler_headers"])
    receipt = validate_success(response, 201)

    assert receipt["net_tons"] == pytest.approx(23.68, abs=1e-6)
    assert receipt["moisture_deduction_tons"] == pytest.approx(0.644, abs=1e-6)
    assert receipt["weighted_moisture_pct"] == pytest.approx(14.65, abs=1e-6)
    assert receipt["weighted_contamination_pct"] == pytest.approx(1.99, abs=1e-6)
    assert receipt["status"] == "SAMPLED"
    assert receipt["declared_grade_code"] == "OCC_11"
    assert receipt["supplier_id"] == supplier["id"]


def test_the_sample_averages_weigh_the_soaked_sublot_at_its_wet_tonnage():
    """PRD §3.2: "Two weighted averages come out of the same pass and both use the
    **pre-deduction wet tonnages** as weights, never the dry tonnages."
    PRD §3.2: "`weighted_moisture_pct` is the sum over sublots of wet tonnage multiplied by
    that sublot's `moisture_pct`, divided by the sum of the wet tonnages, rounded half up to
    two decimal places."
    PRD §3.2: "`weighted_contamination_pct` is the same construction over each sublot's
    `contamination_pct`, rounded half up to two decimal places."

    Design: Corner/calculations/weighted_sample_percentages_use_pre_deduction_wet_weights
    """
    _, po = _confirmed_occ_order()

    receipt = record_receipt(po["id"], [sublot(1, 102.000, 2.000, 40.00, 1.00),
                                        sublot(2, 102.000, 2.000, 12.00, 5.00)],
                             truck_reference="TRK-WET-1")

    assert receipt["net_tons"] == pytest.approx(172.00, abs=1e-6)
    assert receipt["moisture_deduction_tons"] == pytest.approx(28.000, abs=1e-6)
    assert receipt["weighted_moisture_pct"] == pytest.approx(26.00, abs=1e-6)
    assert receipt["weighted_contamination_pct"] == pytest.approx(3.00, abs=1e-6)
