"""Lot registration, stock segregation, filtering, expiration, receipt-created lots."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_lot,
    create_lot_payload,
    get_lot,
    make_approved_order,
    make_private_lot,
    make_product,
    make_public_lots,
    make_site,
    make_unit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

VM = TEST_USERS["vaccine_manager_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


class TestManualLotRegistration:
    def test_manual_public_lot_registration_rejected(self, api):
        """PRD §2.5: "Manual lot registration accepts private stock only; an
        attempt to register a `PUBLIC_VFC` lot directly is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/lot_creation_rejects_public_vfc_stock_type_manual_registration
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        payload = create_lot_payload(
            unit["id"], product["id"], stock_type="PUBLIC_VFC", lot_number="L-PUB"
        )
        resp = api.create_lot(site["id"], payload, VM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unknown_stock_type_enum_rejected(self, api):
        """PRD §2.4: "Enum-typed fields accept only their declared value sets;
        a value outside the declared set is rejected with `ERR_INVALID_ENUM`
        (HTTP 400)."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        payload = create_lot_payload(
            unit["id"], product["id"], stock_type="UNKNOWN_VALUE", lot_number="L-X"
        )
        resp = api.create_lot(site["id"], payload, VM)
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


class TestLotListing:
    def test_lots_filter_by_stock_type(self, api):
        """PRD §4: GET /provider-sites/{id}/lots supports "filters:
        `stock_type`, `status`, `storage_unit_id`, `vaccine_product_id`".
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/get_lots_filter_by_stock_type
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        pub = make_public_lots(site["id"], unit["id"], product["id"], [6, 4])
        make_private_lot(site["id"], unit["id"], product["id"], quantity_on_hand=5)
        resp = api.list_lots(site["id"], VM, params={"stock_type": "PUBLIC_VFC"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"filter stock_type=PUBLIC_VFC must match exactly the 2 public lots, "
            f"got total_count={meta['total_count']}"
        )
        assert all(lot["stock_type"] == "PUBLIC_VFC" for lot in data)
        assert {lot["id"] for lot in data} == set(pub["lot_ids"])


class TestLotExpiration:
    def test_clock_advance_past_expiry_transitions_lot(self, api):
        """PRD §2.10: "Each advance of the clock triggers an expiration sweep:
        every lot still `AVAILABLE` whose manufacturer expiration date now lies
        strictly in the past — the current calendar date is later than the
        lot's `expires_on` — and whose `quantity_on_hand` is still above zero
        transitions to `EXPIRED`, its `quantity_on_hand` is set to zero".

        Design: Corner/endpoints/lot_expiration_auto_transition_via_clock
        """
        set_clock("2026-08-01T00:00:00Z")
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lot = make_private_lot(
            site["id"], unit["id"], product["id"],
            quantity_on_hand=5, expires_on="2026-08-10",
        )
        set_clock("2026-08-11T00:00:00Z")
        reloaded = get_lot(lot["id"])
        assert reloaded["status"] == "EXPIRED"
        assert reloaded["quantity_on_hand"] == 0


class TestAllocationReceiptLotCreation:
    def test_receipt_creates_public_lot_and_links_back(self, api):
        """PRD §3.5: "Posting a receipt creates the physical stock: a new lot
        with `stock_type` `PUBLIC_VFC`, `quantity_on_hand` equal to
        `quantity_doses`, status `AVAILABLE`, and `received_via_order_id`
        pointing at the order; the receipt's own `lot_id` is set to the
        created lot."

        Design: Corner/endpoints/allocation_receipt_creates_lot_and_links
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        order, line = make_approved_order(site["id"], product["id"], 5)
        receipt = validate_success(
            api.create_allocation_receipt(
                site["id"], order["id"],
                {
                    "order_line_id": line["id"],
                    "storage_unit_id": unit["id"],
                    "lot_number": "LOT-X",
                    "expires_on": "2027-06-30",
                    "quantity_doses": 5,
                },
                VM,
            ),
            expected_status=201,
        )
        assert receipt["lot_id"]
        lot = get_lot(receipt["lot_id"])
        assert_lot(lot)
        assert lot["stock_type"] == "PUBLIC_VFC"
        assert lot["quantity_on_hand"] == 5
        assert lot["status"] == "AVAILABLE"
        assert lot["received_via_order_id"] == order["id"]
