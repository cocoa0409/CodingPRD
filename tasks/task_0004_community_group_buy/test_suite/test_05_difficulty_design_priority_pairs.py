"""Difficulty-design coverage: Rule 5 — Validation priority conflicts.

Two instances:
  - campaign_state_vs_flash_stock_priority
  - cold_chain_safety_vs_warehouse_referential
"""
import pytest
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_community, create_supplier, create_customer, create_active_leader,
    create_pickup_point, create_warehouse, create_group_buy_campaign,
    join_campaign, pay_order, close_campaign,
    setup_flash_scenario,
    create_flash_purchase_payload, create_flash_campaign_payload,
    create_plan_shipments_payload,
    ADMIN, make_customer_headers, make_supplier_headers,
)


class TestCampaignStateVsFlashStockPriority:
    """# difficulty: priority_pair_validation_conflict/campaign_state_vs_flash_stock_priority"""

    def _exhaust_a_flash_campaign(self):
        sc = setup_flash_scenario(total_stock=1, tier_caps=[{"tier": 0, "max_units": 10}])
        cust2 = get_success_data(api_client.create_customer(
            {"community_id": sc["community"]["id"], "display_name": "Cust2"},
            ADMIN,
        ))
        # Cust1 buys the only unit -> EXHAUSTED
        get_success_data(api_client.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=1),
            make_customer_headers(sc["customer"]["id"]),
        ))
        return sc, cust2

    def test_exhausted_campaign_returns_not_open_not_stock_depleted(self, api):
        """PRD §2.9: "On a flash purchase, the flash campaign's open-window
        check fires before the anti-oversell stock check, so a campaign
        whose status is EXHAUSTED (current period below closes_at_period
        and remaining_units at zero) or CLOSED (current period at or beyond
        closes_at_period) surfaces as ERR_FLASH_CAMPAIGN_NOT_OPEN regardless
        of whether a request would have triggered the stock-depletion path."

        Claim: after stock is exhausted, a second purchase fails with
        ERR_FLASH_CAMPAIGN_NOT_OPEN (priority 8.5), not
        ERR_FLASH_STOCK_DEPLETED (priority 17).
        """
        sc, cust2 = self._exhaust_a_flash_campaign()
        res = api.flash_purchase(
            sc["flash_campaign"]["id"],
            create_flash_purchase_payload(requested_units=1),
            make_customer_headers(cust2["id"]),
        )
        validate_error(res, "ERR_FLASH_CAMPAIGN_NOT_OPEN")

    def test_exhausted_status_visible_after_purchase(self, api):
        """PRD §3.5: "A flash purchase by a Customer carries a single
        requested_units integer. The platform first verifies that the
        campaign is OPEN; an EXHAUSTED or CLOSED campaign rejects with
        ERR_FLASH_CAMPAIGN_NOT_OPEN regardless of the requested amount."
        PRD §3.5: "When remaining_units drops to zero as a result, the
        campaign's status advances to EXHAUSTED."

        Claim: after the only stock unit is bought, the campaign's
        status is EXHAUSTED — establishing the precondition for the
        priority-pair test above.
        """
        sc, _ = self._exhaust_a_flash_campaign()
        fc = get_success_data(api_client.get_flash_campaign(sc["flash_campaign"]["id"], ADMIN))
        assert fc["status"] == "EXHAUSTED"
        assert fc["remaining_units"] == 0


class TestColdChainSafetyVsWarehouseReferential:
    """# difficulty: priority_pair_validation_conflict/cold_chain_safety_vs_warehouse_referential"""

    def _setup_cold_sku_with_disabled_non_cold_warehouse(self):
        community = create_community(region_code="RC1")
        cust = create_customer(community["id"], display_name="Cust1")
        supplier = create_supplier(name="S1")
        # Single warehouse: DISABLED + cold_chain_capable=False
        # → no cold-capable warehouse exists at all (priority 9 fires)
        # → no ACTIVE warehouse exists either (priority 10 would fire)
        create_warehouse(supplier["id"], region_code="RC1",
                          cold_chain_capable=False,
                          handling_periods=1, cold_handling_periods=1,
                          initial_status="DISABLED")
        pickup = create_pickup_point(community["id"], capacity_packages=5,
                                       cold_storage_capable=True)
        leader = create_active_leader(community["id"], display_name="L1")
        campaign = create_group_buy_campaign(
            leader["id"], supplier["id"],
            sku="COLD1", cold_chain_required=True,
            unit_price_cents=100,
            discount_tiers=[{"min_participants": 1, "discount_basis_points": 0}],
            opens_at_period=0, deadline_period=100,
        )
        order = join_campaign(campaign["id"], cust["id"],
                              line_items=[{"sku": "COLD1", "unit_price_cents": 100, "quantity": 1}])
        order = pay_order(order["id"], cust["id"])
        close_campaign(campaign["id"], leader["id"])
        return supplier, pickup, order

    def test_cold_chain_required_wins_over_no_warehouse_available(self, api):
        """PRD §2.9: "Plan-shipments enforces a second priority pair: the
        cold-chain safety check runs before the candidate-warehouse pool
        check. If the request includes any line with a cold-chain SKU and
        the supplier owning that SKU has no warehouse with cold_chain_capable
        set to true (regardless of warehouse status), the rejection is
        ERR_COLD_CHAIN_REQUIRED. Only when at least one cold-capable
        warehouse exists does the empty-pool check apply."

        Claim: when both checks would fire (no cold-capable AND no ACTIVE
        warehouse), ERR_COLD_CHAIN_REQUIRED takes precedence over
        ERR_NO_WAREHOUSE_AVAILABLE.
        """
        supplier, pickup, order = self._setup_cold_sku_with_disabled_non_cold_warehouse()
        res = api.plan_shipments(
            order["id"],
            create_plan_shipments_payload(
                pickup["id"],
                [{"sku": "COLD1", "quantity": 1}],
            ),
            make_supplier_headers(supplier["id"]),
        )
        validate_error(res, "ERR_COLD_CHAIN_REQUIRED")

    def test_cold_chain_required_returns_http_422(self, api):
        """PRD §2.9 + §5: "the rejection is ERR_COLD_CHAIN_REQUIRED."
        PRD §5 error catalogue lists ERR_COLD_CHAIN_REQUIRED at HTTP 422.

        Claim: HTTP 422 accompanies the ERR_COLD_CHAIN_REQUIRED response.
        """
        supplier, pickup, order = self._setup_cold_sku_with_disabled_non_cold_warehouse()
        res = api.plan_shipments(
            order["id"],
            create_plan_shipments_payload(
                pickup["id"],
                [{"sku": "COLD1", "quantity": 1}],
            ),
            make_supplier_headers(supplier["id"]),
        )
        assert res.status_code == 422
        validate_error(res, "ERR_COLD_CHAIN_REQUIRED", expected_status=422)
