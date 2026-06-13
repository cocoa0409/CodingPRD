"""Revenue-share settlement and spoilage costing — the two dual-variant calcs.

Queue A (Difficulty): dual_variant_calc instances (revenue GROSS/NET, spoilage FIFO/WEIGHTED_AVG).
Queue B (Corner): calculations/spoilage_fifo_variant_cost.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    assert_revenue_share_statement, assert_waste_record,
    create_waste_record_payload, TEST_USERS,
)
from test_helpers.fixtures import (
    setup_settled_event_with_sales_and_waste, setup_stand_with_two_bun_lots,
)

RUNNER = TEST_USERS["runner_headers"]


# ===========================================================================
# Queue A — revenue_share_gross_vs_net_basis
# Same gross 4922 + waste 300: GROSS share 984, NET share 924.
# ===========================================================================
def test_settlement_gross_basis_ignores_waste(api):
    """PRD §3.9: "Under the GROSS basis, the base is the snapshot gross sales and
    waste is ignored, so venue_share_cents is the gross sales multiplied by the
    venue's venue_share_pct divided by 100, rounded half-up to whole cents."
    PRD §3.9: "The operator's net take, operator_net_cents, is the snapshot gross
    sales minus the computed venue_share_cents."

    gross 4922, pct 20 -> round(984.4)=984; operator_net = 4922-984 = 3938.

    Design: Difficulty/dual_variant_calc/revenue_share_gross_vs_net_basis
    """
    s = setup_settled_event_with_sales_and_waste(share_basis="GROSS", venue_share_pct=20, service_fee_pct=7)
    stmt = s["statement"]
    assert_revenue_share_statement(stmt)
    assert stmt["gross_sales_cents"] == 4922, f"gross {stmt['gross_sales_cents']}"
    assert stmt["waste_cost_cents"] == 300, f"waste {stmt['waste_cost_cents']}"
    assert stmt["venue_share_cents"] == 984, f"share {stmt['venue_share_cents']}"
    assert stmt["operator_net_cents"] == 3938, f"net {stmt['operator_net_cents']}"


def test_settlement_net_basis_subtracts_waste_from_base(api):
    """PRD §3.9: "Under the NET basis, the base is instead the greater of zero and
    the snapshot gross sales minus the snapshot waste cost, so venue_share_cents is
    that floored-at-zero net base multiplied by the venue's venue_share_pct divided
    by 100, rounded half-up to whole cents; because spoilage shrinks the base,
    identical gross sales yield a smaller venue share under NET than under GROSS."

    gross 4922, waste 300, pct 20 -> base 4622, round(924.4)=924 (< the 984 GROSS share).

    Design: Difficulty/dual_variant_calc/revenue_share_gross_vs_net_basis
    """
    s = setup_settled_event_with_sales_and_waste(share_basis="NET", venue_share_pct=20, service_fee_pct=7)
    stmt = s["statement"]
    assert stmt["gross_sales_cents"] == 4922
    assert stmt["waste_cost_cents"] == 300
    assert stmt["venue_share_cents"] == 924, f"NET share expected 924, got {stmt['venue_share_cents']}"
    assert stmt["operator_net_cents"] == 4922 - 924


# ===========================================================================
# Queue A — spoilage_fifo_vs_weighted_avg_costing
# Same 120-bun SPILLAGE over lots 100@30 (older) + 100@50: FIFO 4000, WEIGHTED_AVG 4800.
# ===========================================================================
def test_spoilage_weighted_avg_blends_unit_cost(api):
    """PRD §3.6: "Under the WEIGHTED_AVG policy, a single blended unit cost is
    formed by summing, across the lots, each lot's remaining quantity at the time
    of the waste multiplied by its unit_cost_cents, dividing that total by the sum
    of those remaining quantities, and rounding the quotient half-up to whole
    cents; the waste cost is then that rounded weighted-average unit cost
    multiplied by the waste quantity, independent of lot ordering."

    (100*30 + 100*50)/200 = 40; cost = 120*40 = 4800.

    Design: Difficulty/dual_variant_calc/spoilage_fifo_vs_weighted_avg_costing
    """
    s = setup_stand_with_two_bun_lots(spoilage_valuation="WEIGHTED_AVG")
    resp = api.create_waste_record(create_waste_record_payload(s["stand"]["id"], s["product"]["id"], "SPILLAGE", 120), RUNNER)
    data = validate_success(resp, 201)
    assert_waste_record(data)
    assert data["cost_cents"] == 4800, f"expected 4800 (weighted-avg), got {data['cost_cents']}"


def test_spoilage_weighted_avg_bumps_event_waste_cost(api):
    """PRD §3.6: "Posting a waste record computes its cost_cents, increases the
    parent event's waste_cost_cents by that amount".

    WEIGHTED_AVG cost 4800 -> event.waste_cost_cents == 4800.

    Design: Difficulty/dual_variant_calc/spoilage_fifo_vs_weighted_avg_costing
    """
    s = setup_stand_with_two_bun_lots(spoilage_valuation="WEIGHTED_AVG")
    validate_success(api.create_waste_record(create_waste_record_payload(s["stand"]["id"], s["product"]["id"], "SPILLAGE", 120), RUNNER), 201)
    event = validate_success(api.get_event(s["event"]["id"], TEST_USERS["manager_headers"]), 200)
    assert event["waste_cost_cents"] == 4800, f"expected 4800, got {event['waste_cost_cents']}"


# ===========================================================================
# Queue B — calculations/spoilage_fifo_variant_cost (the FIFO branch).
# Same 120-bun SPILLAGE over 100@30 + 100@50 costs 4000 = 100*30 + 20*50.
# ===========================================================================
def test_spoilage_fifo_consumes_oldest_lot_cost_first(api):
    """PRD §3.6: "Under the FIFO policy, the candidate lots are walked oldest
    created_at first and the cost is accumulated as the units taken from each
    consumed lot multiplied by that lot's unit_cost_cents, continuing until the
    full waste quantity has been costed; the cost therefore depends on lot
    ordering."

    120 buns over 100@30 then 100@50 -> 100*30 + 20*50 = 4000.

    Design: Corner/calculations/spoilage_fifo_variant_cost
    """
    s = setup_stand_with_two_bun_lots(spoilage_valuation="FIFO")
    resp = api.create_waste_record(create_waste_record_payload(s["stand"]["id"], s["product"]["id"], "SPILLAGE", 120), RUNNER)
    data = validate_success(resp, 201)
    assert data["cost_cents"] == 4000, f"expected 4000 (FIFO), got {data['cost_cents']}"
