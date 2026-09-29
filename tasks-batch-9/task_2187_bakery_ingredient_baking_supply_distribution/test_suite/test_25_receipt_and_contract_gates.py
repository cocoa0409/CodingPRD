"""Receipt gates, the missing quote and an exact commitment draw (PRD §2.8, §3.1, §3.3, §3.5)."""

from test_helpers import (
    ApiErrorId,
    add_contract_line,
    activate_contract,
    add_order_line,
    api_client,
    create_customer,
    create_lot_payload,
    create_order_line_payload,
    create_product,
    create_zone,
    draft_contract,
    read_customer,
    offer_contract,
    open_order,
    publish_index_quote,
    read_contract,
    read_contract_line,
    read_order,
    read_order_line,
    read_zone,
    schedule_zone_lockout,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PC, WO, buyer_headers

EPOCH = "2026-08-01T00:00:00Z"

GLUTEN_SKU = {
    "sku": "FLR-MISMATCH-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


class TestZoneDedicationAtReceipt:
    """Two rows are compared, and a mismatch stores nothing."""

    def test_gluten_flour_cannot_be_put_away_into_a_dairy_zone(self):
        """PRD §2.8: "At receipt, a lot may only enter a zone whose `allergen_class` is
        exactly equal to the `allergen_class` of the lot's product; a mismatch is
        rejected with `ERR_ALLERGEN_ZONE_MISMATCH` (HTTP 422)."

        PRD §3.5: "A successful receipt recomputes the zone's `on_hand_lb`, which is
        the total of `quantity_on_hand_lb` over the lots stored in that zone whose
        status is `AVAILABLE` or `QUARANTINED`."

        Design: Corner/validations/corner_val_lot_receipt_into_mismatched_zone_rejected
        """
        set_clock(EPOCH)
        flour = create_product(GLUTEN_SKU)
        dairy_zone = create_zone(zone_code="Z-DRY", allergen_class="DAIRY")

        response = api_client.create_lot(
            create_lot_payload(
                flour["id"], dairy_zone["id"],
                lot_code="LOT-BAD-0001",
                manufactured_on="2026-07-01T00:00:00Z",
                quantity_received_lb=5000,
            ),
            WO,
        )

        validate_error(response, ApiErrorId.ERR_ALLERGEN_ZONE_MISMATCH)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        assert read_zone(dairy_zone["id"])["on_hand_lb"] == 0, (
            "A refused receipt adds no pounds to the zone"
        )
        lots, _meta = validate_paginated(
            api_client.list_lots(WO, params={"product_id": flour["id"]})
        )
        assert lots == [], (
            f"Expected no lot of that SKU to have been stored, got {len(lots)}"
        )


class TestSanitationLockoutIsClosed:
    """The end instant belongs to the lockout, unlike a route window's end instant."""

    def test_a_receipt_at_exactly_the_lockout_end_is_refused_and_one_second_later_is_not(self):
        """PRD §3.1: "The lockout is a **closed** interval — both endpoints belong to
        it. When the logical clock instant falls inside that closed interval the zone's
        `status` reads `SANITATION_LOCKOUT`, and otherwise `OPEN`" ... "While a zone is
        inside its lockout window, no lot may be received into it and no quarantined
        lot in it may be released, and both attempts are rejected with
        `ERR_ZONE_LOCKOUT_CONFLICT` (HTTP 409)."

        Design: Corner/validations/corner_val_lot_receipt_on_lockout_end_instant_rejected
        """
        set_clock(EPOCH)
        flour = create_product(dict(GLUTEN_SKU, sku="FLR-LOCK-30"))
        zone = create_zone(zone_code="Z-LOCK", allergen_class="GLUTEN")
        schedule_zone_lockout(
            zone["id"], "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z"
        )
        set_clock("2026-09-02T00:00:00Z")
        payload = create_lot_payload(
            flour["id"], zone["id"],
            lot_code="LOT-LOCK-0001",
            manufactured_on="2026-08-01T00:00:00Z",
            quantity_received_lb=5000,
        )

        response = api_client.create_lot(payload, WO)

        validate_error(response, ApiErrorId.ERR_ZONE_LOCKOUT_CONFLICT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        locked = read_zone(zone["id"])
        assert locked["status"] == "SANITATION_LOCKOUT", (
            f"The end instant is inside the closed interval, got {locked['status']}"
        )
        assert locked["on_hand_lb"] == 0, (
            f"Expected no pounds stored, got {locked['on_hand_lb']}"
        )

        set_clock("2026-09-02T00:00:01Z")
        accepted = validate_success(api_client.create_lot(payload, WO), 201)

        assert accepted["status"] == "AVAILABLE", (
            f"One second past the end the zone reopens, got {accepted['status']}"
        )
        assert read_zone(zone["id"])["status"] == "OPEN", (
            "The clock has left the closed interval"
        )


class TestNoPrevailingQuoteRefusesSubmission:
    """An index-linked SKU with only a future quote cannot be priced at all."""

    def test_submission_fails_rather_than_falling_back_to_the_list_price(self):
        """PRD §3.3: "Where an index quote is required and none has been published with
        an `effective_on` at or before the applicable observation date, the submission
        is rejected with `ERR_INDEX_QUOTE_MISSING` (HTTP 422)."

        PRD §3.3: "Lines are added to an order while it remains `UNPRICED`, each naming
        a `product_id` and a `quantity_lb` strictly greater than zero. A new line begins
        with `allocation_status` at `UNALLOCATED`, `unit_price_cents` and
        `extended_cents` at 0"

        Design: Corner/validations/corner_val_missing_quote_before_order_date_rejected_at_submit
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(
            dict(GLUTEN_SKU, sku="FLR-NOQ-30", index_code="HRW_WHEAT")
        )
        publish_index_quote(
            index_code="HRW_WHEAT",
            effective_on="2026-09-05T00:00:00Z",
            price_cents_per_lb=200,
        )
        contract = draft_contract(
            customer,
            term_start_on=EPOCH,
            term_end_on="2026-12-31T00:00:00Z",
            pricing_mode="ORDER_DATE_INDEX",
        )
        contract_line = add_contract_line(
            contract["id"], flour["id"],
            volume_committed_lb=100000,
            basis_cents_per_lb=12,
        )
        offer_contract(contract["id"])
        activate_contract(contract["id"])
        set_clock("2026-08-10T00:00:00Z")
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-20T00:00:00Z",
            contract_id=contract["id"],
        )
        line = add_order_line(customer, order["id"], flour["id"], 1000)

        response = api_client.submit_order(
            order["id"], {}, buyer_headers(customer)
        )

        validate_error(response, ApiErrorId.ERR_INDEX_QUOTE_MISSING)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        unpriced = read_order(order["id"])
        assert unpriced["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {unpriced['pricing_status']}"
        )
        assert unpriced["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {unpriced['fulfillment_status']}"
        )
        untouched = read_order_line(line["id"])
        assert untouched["unit_price_cents"] == 0, (
            f"Expected no price written, got {untouched['unit_price_cents']}"
        )
        assert untouched["extended_cents"] == 0, (
            f"Expected no extension written, got {untouched['extended_cents']}"
        )
        assert read_contract_line(contract_line["id"])["volume_drawn_lb"] == 0, (
            "A refused submission draws no commitment volume"
        )
        assert read_customer(customer["id"])["open_exposure_cents"] == 0, (
            "An UNPRICED order contributes nothing to the exposure ledger"
        )


class TestBulkCapabilityGateOnTheLineWrite:
    """The bagged-only SKU is refused when the line is written, not at allocation."""

    def test_a_bulk_order_will_not_take_a_line_for_a_sku_that_cannot_be_blown(self):
        """PRD §3.3: "If the order's `delivery_mode` is `BULK`, every line's product
        must have `bulk_capable` set to true and the bakery must have a silo registered
        for that SKU; a line that fails either test is rejected with
        `ERR_PRODUCT_NOT_BULK_CAPABLE` (HTTP 422), and that same check runs again at
        allocation time."

        Design: Corner/validations/corner_val_bulk_line_on_non_bulk_capable_sku_rejected
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        bagged_only = create_product(dict(GLUTEN_SKU, sku="FLR-BAGONLY-30"))
        order = open_order(
            customer,
            delivery_mode="BULK",
            requested_delivery_on="2026-09-10T00:00:00Z",
        )

        response = api_client.create_order_line(
            order["id"],
            create_order_line_payload(bagged_only["id"], 5000),
            buyer_headers(customer),
        )

        validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_BULK_CAPABLE)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        assert bagged_only["bulk_capable"] is False, (
            f"The SKU was created without the flag, got {bagged_only['bulk_capable']}"
        )
        assert read_order(order["id"])["subtotal_cents"] == 0, (
            "A refused line leaves the order unpriced at zero"
        )
        lines, _meta = validate_paginated(
            api_client.list_order_lines_of_order(order["id"], buyer_headers(customer))
        )
        assert lines == [], (
            f"Expected no line stored on the order, got {len(lines)}"
        )


class TestDrawingExactlyToTheCommitment:
    """The headroom test is strict-above, and the last pound exhausts the contract."""

    def test_a_thousand_pound_draw_against_a_thousand_pound_commitment_is_permitted(self):
        """PRD §3.3: "A draw may bring a line's `volume_drawn_lb` up to exactly its
        `volume_committed_lb`, which is permitted and exhausts that line; a draw that
        would push it strictly above the commitment is rejected with
        `ERR_CONTRACT_VOLUME_EXCEEDED` (HTTP 409). Once every line of the contract has
        reached its commitment, the contract auto-transitions `ACTIVE → EXHAUSTED` at
        the end of the submission, as §3.2 describes."

        PRD §3.4: "When the product's `index_code` is `NONE` the SKU has no index
        linkage at all, so the settled price is the product's `list_price_cents_per_lb`
        plus the commitment line's `basis_cents_per_lb`"

        Design: Corner/validations/corner_val_draw_exactly_to_commitment_passes_and_exhausts_contract
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(GLUTEN_SKU, sku="FLR-EXACT-30"))
        contract = draft_contract(
            customer,
            term_start_on=EPOCH,
            term_end_on="2026-12-31T00:00:00Z",
            pricing_mode="ORDER_DATE_INDEX",
        )
        contract_line = add_contract_line(
            contract["id"], flour["id"],
            volume_committed_lb=1000,
            basis_cents_per_lb=12,
        )
        offer_contract(contract["id"])
        activate_contract(contract["id"])
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
            contract_id=contract["id"],
        )
        line = add_order_line(customer, order["id"], flour["id"], 1000)

        submitted = submit_order(customer, order["id"])

        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {submitted['pricing_status']}"
        )
        drawn = read_contract_line(contract_line["id"])
        assert drawn["volume_drawn_lb"] == 1000, (
            f"Expected the commitment drawn to the pound, got {drawn['volume_drawn_lb']}"
        )
        exhausted = read_contract(contract["id"])
        assert exhausted["status"] == "EXHAUSTED", (
            f"Expected EXHAUSTED, got {exhausted['status']}"
        )
        assert exhausted["drawn_volume_lb"] == 1000, (
            f"Expected drawn_volume_lb 1000, got {exhausted['drawn_volume_lb']}"
        )
        assert exhausted["committed_volume_lb"] == 1000, (
            f"Expected committed_volume_lb 1000, got {exhausted['committed_volume_lb']}"
        )
        assert read_order_line(line["id"])["unit_price_cents"] == 42, (
            f"Expected 30 list plus 12 basis, got "
            f"{read_order_line(line['id'])['unit_price_cents']}"
        )
        assert submitted["total_cents"] == 43050, (
            f"Expected total 43050, got {submitted['total_cents']}"
        )
