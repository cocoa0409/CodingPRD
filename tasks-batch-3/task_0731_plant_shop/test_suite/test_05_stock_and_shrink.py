"""Stock unit lifecycle, physical cardinality invariant, and OCC on adjust."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    append_care_log, get_orderline_id_for_order,
    TEST_USERS, make_customer_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 9 (instance 2): warranty approval preserves plant cardinality
# -----------------------------------------------------------------------------

class TestWarrantyApprovalPlantCardinalityInvariant:

    def _setup_three_units_and_deliver_one(self, email: str):
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email=email, delivery_zone="ZONE_A")
        driver = create_driver(name=f"drv-{email}")
        plant = create_plant(
            name=f"Cactus-{email}", light_tag="DIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=4000, warranty_days=30,
        )
        su1 = intake_stock_unit(plant["id"], acquisition_date="2026-03-25T00:00:00Z")
        su2 = intake_stock_unit(plant["id"], acquisition_date="2026-03-26T00:00:00Z")
        su3 = intake_stock_unit(plant["id"], acquisition_date="2026-03-27T00:00:00Z")
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        d = dispatch_order(order["id"], driver["id"], "2026-04-05T09:00:00Z", "2026-04-05T11:00:00Z")
        set_clock("2026-04-05T10:00:00Z")
        deliver(d["id"], driver["id"])
        set_clock("2026-04-10T00:00:00Z")
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        return customer, plant, (su1, su2, su3), orderline_id

    def test_warranty_approval_flips_delivered_unit_to_shrink(self, api):
        """PRD §3.5: "the delivered StockUnit.sale_status flips from SOLD first to
        RETURNED and then to SHRINK with shrink_reason of WARRANTY_RETURN".

        Design: Difficulty/compensating_invariant/warranty_approve_preserves_stockunit_cardinality_invariant
        """
        customer, plant, (su1, su2, su3), orderline_id = self._setup_three_units_and_deliver_one("wren1@example.com")
        submitted = get_success_data(api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        ))
        validate_success(api.approve_warranty_claim(submitted["id"], TEST_USERS["horticulturist_headers"]))
        su1_after = get_success_data(api.get_stock_unit(su1["id"], TEST_USERS["manager_headers"]))
        assert su1_after["sale_status"] == "SHRINK"
        assert su1_after["shrink_reason"] == "WARRANTY_RETURN"

    def test_available_count_reflects_only_for_sale_and_healthy_after_shrink(self, api):
        """PRD §3.1: "Plant.available_count is not user-supplied: it is a computed
        integer maintained by the system as the count of StockUnit rows under
        this plant whose sale_status is FOR_SALE and whose health_status is
        either HEALTHY or RECOVERING. Plant.available_count is recomputed on
        every operation that flips a stock unit's sale or health state."
        PRD §2.9: "Approving a warranty claim after delivery flips the delivered
        unit from SOLD to RETURNED and then to SHRINK with shrink_reason of
        WARRANTY_RETURN; because that final state is not FOR_SALE,
        Plant.available_count is unchanged by the warranty cascade."

        Design: Difficulty/compensating_invariant/warranty_approve_preserves_stockunit_cardinality_invariant
        """
        customer, plant, (su1, su2, su3), orderline_id = self._setup_three_units_and_deliver_one("wren2@example.com")
        submitted = get_success_data(api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        ))
        validate_success(api.approve_warranty_claim(submitted["id"], TEST_USERS["horticulturist_headers"]))
        plant_after = get_success_data(api.get_plant(plant["id"], TEST_USERS["manager_headers"]))
        # 2 units remain FOR_SALE + HEALTHY (su2, su3); su1 is SHRINK.
        assert plant_after["available_count"] == 2


# -----------------------------------------------------------------------------
# Cross-cutting: stock-unit OCC (Corner: cross_cutting_complexity_layers)
# -----------------------------------------------------------------------------

class TestStockUnitAdjustOCC:

    def test_stale_stock_unit_version_on_adjust_rejected(self, api):
        """PRD §2.7: "Stock-unit adjustment. The stock-unit adjustment action
        (driven by POST /stock-units/{id}/adjust) requires the client to send a
        non-optional expected_stock_unit_version matching the target StockUnit's
        current version. If a warranty approval cascade has already flipped the
        unit's sale_status (for instance SOLD to SHRINK with shrink_reason of
        WARRANTY_RETURN) since the operator's read, the adjust is rejected with
        ERR_STALE_VERSION (HTTP 412), preventing an operator from overwriting a
        cascade they have not observed."
        PRD §2.5: "version is a non-negative integer that begins at zero at
        creation and increments by exactly one on every subsequent mutation of
        the entity."

        Design: Corner/cross_cutting_complexity_layers/stock_unit_adjust_stale_version_returns_412
        """
        set_clock("2026-04-01T00:00:00Z")
        plant = create_plant(
            name="Sk", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        stock = intake_stock_unit(plant["id"])
        v_at_create = stock["version"]
        # First adjust bumps StockUnit.version (adjust is a mutation of the entity
        # per PRD §2.5, and PRD §3.1 lists adjust as a mutating action on StockUnit).
        r1 = api.adjust_stock_unit(
            stock["id"],
            {"expected_stock_unit_version": v_at_create, "health_status": "RECOVERING"},
            TEST_USERS["manager_headers"],
        )
        validate_success(r1)
        # Now the operator retries with the stale (pre-first-adjust) version.
        r2 = api.adjust_stock_unit(
            stock["id"],
            {"expected_stock_unit_version": v_at_create, "health_status": "DECLINING"},
            TEST_USERS["manager_headers"],
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION.value)
