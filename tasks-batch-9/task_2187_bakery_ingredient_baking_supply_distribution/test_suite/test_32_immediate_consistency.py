"""Derived reads in the same logical instant, and an approval that refuses as a whole (PRD §2.10, §3.4, §3.8)."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    claim_substitution_request,
    create_customer,
    create_product,
    create_zone,
    open_order,
    raise_substitution_request,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_substitution_request,
    receive_lot,
    set_clock,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import AM, PC, QM, WO

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-IMM-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 365,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


class TestEveryDerivedSurfaceAgreesWithTheWriteThatProducedIt:
    """Allocate once, then read the customer, the summary and the lot back."""

    def test_the_exposure_risk_score_summary_and_lot_all_match_in_one_instant(self):
        """PRD §2.10: "Computed aggregate fields — `on_hand_lb` on a zone,
        `committed_volume_lb` and `drawn_volume_lb` on a contract, `planned_load_lb`,
        `utilization_pct` and `stop_count` on a route, `open_exposure_cents` and
        `allergen_risk_score` on a customer — are always full recomputations from their
        current inputs, never incremental adjustments applied to a stored running total."

        PRD §3.5: "On each picked lot, `quantity_reserved_lb` increases by the line's
        `quantity_lb` and `quantity_on_hand_lb` decreases by the same amount, so the
        conservation invariant of §2.9 holds unchanged." ... "Finally the bakery's
        `allergen_risk_score` is recomputed on the in-flight basis and its `risk_tier`
        re-derived, and the order's `version` increments by 1."

        PRD §3.4: "A bakery's `open_exposure_cents` is the total of `total_cents` over
        every one of its orders whose `pricing_status` is either `PROVISIONAL` or `FINAL`"

        Design: Corner/consistency_model/corner_consistency_immediate_derived_reads_agree_with_the_write_response
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-IMM-30"))
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        lot = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-IMM-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=10000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(customer, order["id"], flour["id"], 4000)
        submitted = submit_order(customer, order["id"])

        allocated = allocate_order(order["id"])

        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"The write response already reports the new state, got "
            f"{allocated['fulfillment_status']}"
        )
        assert allocated["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {allocated['pricing_status']}"
        )
        assert allocated["total_cents"] == 121155, (
            f"Expected total 121155, got {allocated['total_cents']}"
        )
        assert allocated["version"] > submitted["version"], (
            f"Every write increments the version, got {allocated['version']} after "
            f"{submitted['version']}"
        )
        standing = validate_success(api_client.get_customer(customer["id"], AM), 200)
        assert standing["open_exposure_cents"] == 121155, (
            f"Expected the exposure recomputed already, got "
            f"{standing['open_exposure_cents']}"
        )
        assert float(standing["allergen_risk_score"]) == 55.00, (
            f"Expected 55.00, got {standing['allergen_risk_score']}"
        )
        assert standing["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {standing['risk_tier']}"
        )
        summary = validate_success(
            api_client.get_order_pricing_summary(order["id"], PC), 200
        )
        assert summary["subtotal_cents"] == 118200, (
            f"Expected 120000 less the 1.5% tier, got {summary['subtotal_cents']}"
        )
        assert summary["fuel_surcharge_cents"] == 2955, (
            f"Expected 2.5% of 118200, got {summary['fuel_surcharge_cents']}"
        )
        assert summary["volume_rebate_cents"] == 0, (
            f"Expected no rebate below 500000, got {summary['volume_rebate_cents']}"
        )
        assert summary["tech_attach_fee_cents"] == 0, (
            f"No engagement is attached, got {summary['tech_attach_fee_cents']}"
        )
        assert summary["total_cents"] == 121155, (
            f"Expected total 121155, got {summary['total_cents']}"
        )
        reserved = read_lot(lot["id"])
        assert reserved["quantity_on_hand_lb"] == 6000, (
            f"Expected 6000 on hand, got {reserved['quantity_on_hand_lb']}"
        )
        assert reserved["quantity_reserved_lb"] == 4000, (
            f"Expected 4000 reserved, got {reserved['quantity_reserved_lb']}"
        )


class TestAnApprovalThatCannotFinishDoesNotStart:
    """Hop two finds no lot, so hop one is nowhere to be seen afterwards."""

    def test_the_line_price_exposure_and_risk_score_are_all_untouched(self):
        """PRD §3.8: "On success the request moves `UNDER_REVIEW → APPROVED` and five hops
        fire in order." ... "the rotation selector of §3.5 re-picks a lot of the new product
        and re-reserves it; if no eligible lot of the new product exists, the approval is
        rejected with `ERR_NO_ELIGIBLE_LOT`."

        PRD §3.5: "Splitting a line across two lots is not permitted — one lot must cover
        the whole line by itself"

        Design: Corner/consistency_model/corner_consistency_failed_hop_two_rolls_back_hop_one_atomically
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        ordered = create_product(dict(FLOUR_30, sku="FLR-ATA-30"))
        premium = create_product(
            dict(FLOUR_30, sku="FLR-ATB-45", list_price_cents_per_lb=45)
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        stocked_lot = receive_lot(
            ordered["id"], zone["id"], lot_code="LOT-ATA-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=20000,
        )
        thin_lot = receive_lot(
            premium["id"], zone["id"], lot_code="LOT-ATB-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=1000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], ordered["id"], 4000)
        submit_order(customer, order["id"])
        allocated = allocate_order(order["id"])
        request = raise_substitution_request(
            line["id"], premium["id"], allocated["version"],
            rationale="Premium flour offered while the base SKU is short",
        )
        claim_substitution_request(request["id"])

        response = api_client.approve_substitution_request(request["id"], {}, QM)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        held = read_substitution_request(request["id"])
        assert held["status"] == "UNDER_REVIEW", (
            f"Expected the request still UNDER_REVIEW, got {held['status']}"
        )
        assert held["decided_by_user_id"] == "qm-1", (
            f"Expected the claiming manager retained, got {held['decided_by_user_id']}"
        )
        untouched = read_order_line(line["id"])
        assert untouched["product_id"] == ordered["id"], (
            f"Hop one never landed, got {untouched['product_id']}"
        )
        assert untouched["substituted_from_product_id"] is None, (
            f"Expected no substitution recorded, got "
            f"{untouched['substituted_from_product_id']}"
        )
        assert untouched["unit_price_cents"] == 30, (
            f"Expected the original unit price, got {untouched['unit_price_cents']}"
        )
        assert untouched["lot_id"] == stocked_lot["id"], (
            f"Expected the original reservation intact, got {untouched['lot_id']}"
        )
        assert read_lot(stocked_lot["id"])["quantity_reserved_lb"] == 4000, (
            "The original lot keeps the line's pounds"
        )
        assert read_lot(thin_lot["id"])["quantity_reserved_lb"] == 0, (
            "The thin lot reserved nothing"
        )
        assert read_order(order["id"])["total_cents"] == 121155, (
            "No partial reprice survives the refusal"
        )
        after = read_customer(customer["id"])
        assert after["open_exposure_cents"] == 121155, (
            f"Expected the exposure unchanged, got {after['open_exposure_cents']}"
        )
        assert float(after["allergen_risk_score"]) == 55.00, (
            f"Expected 55.00, got {after['allergen_risk_score']}"
        )
        assert after["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {after['risk_tier']}"
        )
