"""Co-pack contract fulfillment, shortfall penalty, OCC amend (PRD §3.2)."""
import pytest

from test_helpers import (
    allocate,
    create_contract,
    create_shipment,
    get_success_data,
    setup_active_contract,
    setup_completed_run,
    validate_success,
)
from test_helpers.fixtures import PM, WH
from test_helpers.factories import create_product_payload, create_customer_payload


def _deliver_contract_shipment(api, contract, customer, lot_id, units,
                               shipment_code="SH-C1"):
    shipment = create_shipment(customer["id"], shipment_code=shipment_code,
                               contract_id=contract["id"])
    allocate(shipment["id"], lot_id, units)
    get_success_data(api.load_shipment(shipment["id"], WH))
    get_success_data(api.dispatch_shipment(shipment["id"], WH))
    return validate_success(api.deliver_shipment(shipment["id"], WH))


class TestContractShortfallPenalty:
    def test_shortfall_penalty_pinned_evaluation_order(self, api):
        """PRD §3.2: "first the contract's fulfillment_pct is computed as
        delivered_units divided by committed_units, multiplied by 100,
        rounded half-up to 2 decimal places; then a tier rate is selected —
        0.10 when fulfillment_pct is at least 90, 0.20 when fulfillment_pct
        is at least 50 but less than 90, and 0.35 when fulfillment_pct is
        below 50; then shortfall_penalty_cents is the shortfall in units
        (committed minus delivered) multiplied by unit_price_cents multiplied
        by that tier rate."

        4000/10000 delivered -> pct 40.0 (< 50 -> 0.35); penalty
        (10000-4000) * 250 * 0.35 = 525000.

        Design: Difficulty/combinatorial_formula/contract_shortfall_penalty_pinned_order
        """
        ctx = setup_active_contract(committed_units=10000,
                                    unit_price_cents=250,
                                    activate_at="2026-08-05T00:00:00Z")
        product, customer, contract = (ctx["product"], ctx["customer"],
                                       ctx["contract"])
        run_ctx = setup_completed_run(
            product=product,
            run_code="R-C1", planned_units=4000, actual_units=4000,
            mix_metered_litres=200.0, scheduled_start="2026-08-05T10:00:00Z",
            booking_window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            clock="2026-08-05T08:00:00Z")
        _deliver_contract_shipment(api, contract, customer,
                                   run_ctx["lot"]["id"], 4000)
        resp = api.cancel_contract(contract["id"], PM)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELED"
        assert cancelled["delivered_units"] == 4000
        assert cancelled["fulfillment_pct"] == pytest.approx(40.0, abs=0.005)
        assert cancelled["shortfall_penalty_cents"] == 525000

    def test_shortfall_penalty_null_when_canceled_from_draft(self, api):
        """PRD §3.2: "Cancelling from DRAFT or SUBMITTED leaves
        shortfall_penalty_cents null."

        Design: Difficulty/combinatorial_formula/contract_shortfall_penalty_pinned_order
        """
        product = get_success_data(api.create_product(
            create_product_payload(sku_code="CP-BAR", co_pack_only=True),
            PM), 201)
        customer = get_success_data(api.create_customer(
            create_customer_payload(customer_code="PL-1",
                                    display_name="Big Retailer",
                                    kind="PRIVATE_LABEL"), PM), 201)
        contract = create_contract(customer["id"], product["id"],
                                   committed_units=1000, unit_price_cents=100)
        cancelled = validate_success(api.cancel_contract(contract["id"], PM))
        assert cancelled["status"] == "CANCELED"
        assert cancelled["shortfall_penalty_cents"] is None


class TestFulfillmentPctPrecision:
    def test_fulfillment_pct_two_dp_precision(self, api):
        """PRD §3.2: fulfillment_pct is "delivered_units divided by
        committed_units, multiplied by 100, rounded half-up to 2 decimal
        places". 1/3 delivered -> 33.33; pct below 50 selects the 0.35 tier,
        so penalty == (3-1)*100*0.35 == 70.

        Design: Corner/calculations/fulfillment_pct_two_dp_precision
        """
        ctx = setup_active_contract(committed_units=3, unit_price_cents=100,
                                    activate_at="2026-08-05T08:00:00Z")
        run_ctx = setup_completed_run(
            product=ctx["product"],
            run_code="R-P3", planned_units=3, actual_units=3,
            mix_metered_litres=0.5, scheduled_start="2026-08-05T10:00:00Z",
            booking_window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            clock="2026-08-05T08:00:00Z")
        _deliver_contract_shipment(api, ctx["contract"], ctx["customer"],
                                   run_ctx["lot"]["id"], 1,
                                   shipment_code="SH-P3")
        cancelled = validate_success(api.cancel_contract(ctx["contract"]["id"], PM))
        assert cancelled["fulfillment_pct"] == pytest.approx(33.33, abs=0.005)
        assert cancelled["shortfall_penalty_cents"] == 70
        assert cancelled["status"] == "CANCELED"


class TestDeliveryFulfillsContract:
    def test_delivery_fulfills_contract_at_exact_boundary(self, api):
        """PRD §3.2: "when delivered_units reaches or exceeds
        committed_units (exact equality fulfills), the contract
        auto-transitions ACTIVE → FULFILLED." 1000 of 1000 delivered ->
        fulfillment_pct 100.0 and status FULFILLED.

        Design: Difficulty/transitive_cascade/delivery_fulfills_contract_cascade
        """
        ctx = setup_active_contract(committed_units=1000, unit_price_cents=100,
                                    contract_code="CT-F",
                                    activate_at="2026-08-05T08:00:00Z")
        run_ctx = setup_completed_run(
            product=ctx["product"],
            run_code="R-F", planned_units=1500, actual_units=1500,
            mix_metered_litres=80.0, scheduled_start="2026-08-05T10:00:00Z",
            booking_window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            clock="2026-08-05T08:00:00Z")
        delivered = _deliver_contract_shipment(api, ctx["contract"],
                                               ctx["customer"],
                                               run_ctx["lot"]["id"], 1000,
                                               shipment_code="SH-F")
        assert delivered["status"] == "DELIVERED"
        contract = get_success_data(api.get_contract(ctx["contract"]["id"], PM))
        assert contract["delivered_units"] == 1000
        assert contract["fulfillment_pct"] == pytest.approx(100.0, abs=0.005)
        assert contract["status"] == "FULFILLED"

    def test_delivery_accumulates_delivered_units(self, api):
        """PRD §3.8: "When the shipment carries a contract_id, delivery also
        adds the sum of the allocation units to the contract's
        delivered_units and recomputes fulfillment_pct"."

        1000 of 2000 delivered: delivered_units 1000, pct 50.0, contract
        remains ACTIVE.

        Design: Difficulty/transitive_cascade/delivery_fulfills_contract_cascade
        """
        ctx = setup_active_contract(committed_units=2000, unit_price_cents=100,
                                    activate_at="2026-08-05T08:00:00Z")
        run_ctx = setup_completed_run(
            product=ctx["product"],
            run_code="R-F2", planned_units=1500, actual_units=1500,
            mix_metered_litres=80.0, scheduled_start="2026-08-05T10:00:00Z",
            booking_window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            clock="2026-08-05T08:00:00Z")
        _deliver_contract_shipment(api, ctx["contract"], ctx["customer"],
                                   run_ctx["lot"]["id"], 1000,
                                   shipment_code="SH-F2")
        contract = get_success_data(api.get_contract(ctx["contract"]["id"], PM))
        assert contract["delivered_units"] == 1000
        assert contract["fulfillment_pct"] == pytest.approx(50.0, abs=0.005)
        assert contract["status"] == "ACTIVE"
