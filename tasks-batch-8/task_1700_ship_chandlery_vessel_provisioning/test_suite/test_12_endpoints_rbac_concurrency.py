"""Endpoint, error, RBAC, OCC, and consistency corner cases.

Covers corner-design §endpoints (pagination + filtering, FK reverse lookups,
response envelope), §errors (invoicable gate, complaint quantity cap),
§rbac (role and ownership denials), §cross_cutting_layers (OCC stale-version
on quotation revise and stock adjustment; immediate consistency on invoice
issuance), and §consistency_model (post-confirm read-after-write).
"""
from test_helpers import (
    FINANCE,
    OPS,
    TEST_USERS,
    ApiErrorId,
    api_client,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    setup_accepted_order,
    setup_delivered_order,
    setup_invoiced_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    confirm_delivery,
    create_agent,
    create_catalog_item,
    create_scheduled_delivery,
    create_sent_quotation,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    dispatch_delivery,
    file_complaint,
    set_clock,
)

SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def _water(sku, lot_code):
    return (
        dict(sku=sku, name="Water 1L", category="PROVISIONS", bonded_eligible=False,
             requires_cold_chain=False, base_price_cents=120, duty_rate_pct=0),
        dict(lot_code=lot_code, received_qty=10000),
    )


# ===========================================================================
# endpoints
# ===========================================================================

class TestCatalogListPaginationAndFilter:
    def test_catalog_list_pagination_and_filter(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
        of 100; `offset` defaults to 0. Lists are always sorted by `created_at`
        ascending. The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`." PRD §3.1: "The catalog list
        supports filtering by `category` and `requires_cold_chain` alongside
        pagination."

        3 PROVISIONS + 1 BONDED items: category=PROVISIONS&limit=2&offset=0 =>
        2 rows, total_count 3, has_more true; offset=2 => 1 row, has_more
        false; category=BONDED => exactly the bonded item.

        Design: Corner/endpoints/catalog_list_pagination_and_filter
        """
        for i in range(1, 4):
            create_catalog_item(sku=f"PG-{i}", name=f"I{i}", category="PROVISIONS",
                                base_price_cents=100)
        create_catalog_item(sku="PG-4", name="I4", category="BONDED",
                            bonded_eligible=True, base_price_cents=100)

        page1, meta1 = validate_paginated(api_client.list_catalog_items(
            SALES, params={"category": "PROVISIONS", "limit": 2, "offset": 0},
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_catalog_items(
            SALES, params={"category": "PROVISIONS", "limit": 2, "offset": 2},
        ))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        bonded, meta3 = validate_paginated(api_client.list_catalog_items(
            SALES, params={"category": "BONDED"},
        ))
        assert len(bonded) == 1
        assert bonded[0]["sku"] == "PG-4"


class TestFkReverseLookupsReturnArrays:
    def test_fk_reverse_lookups_return_arrays(self, api):
        """PRD §3.4: "the orders created from a quotation can be listed as an
        array of zero or one element". Before accept: GET
        /quotations/{id}/orders => [] (empty array, not 404). GET
        /requisitions/{id}/quotations => array of length 1 holding the
        quotation.

        Design: Corner/endpoints/fk_reverse_lookups_return_arrays
        """
        agent = create_agent(name="Agent AT")
        water = create_catalog_item(
            sku="WATER-C21", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-C21", received_qty=10000)
        call = create_vessel_call(agent["id"], vessel_name="MV Tethys")
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=50)
        quo = create_sent_quotation(req["id"], water["id"], qty=50, unit_price_cents=120)

        orders = get_success_data(api_client.list_quotation_orders(quo["id"], SALES))
        assert orders == [], "Empty array (not 404) before accept"

        quotations = get_success_data(api_client.list_quotations(req["id"], SALES))
        assert len(quotations) == 1
        assert quotations[0]["id"] == quo["id"]


class TestResponseEnvelopeShape:
    def test_response_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format" — meta.api_request_id,
        meta.api_request_timestamp, response_type object|array, and data. Error
        responses carry response_type 'error' and data.error_id + data.message.

        Design: Corner/endpoints/response_envelope_shape
        """
        create_catalog_item(sku="ENV-1", name="Envelope probe", category="DECK",
                            base_price_cents=100)
        resp = api_client.list_catalog_items(OPS)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert isinstance(body["data"], list)

        err = api_client.get_vessel_call(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", OPS,
        )
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert isinstance(err_body["data"]["error_id"], str)
        assert isinstance(err_body["data"]["message"], str)


# ===========================================================================
# errors
# ===========================================================================

class TestErrorOrderNotInvoicableBeforeDelivery:
    def test_error_order_not_invoicable_before_delivery(self, api):
        """PRD §3.9: "Once an order's fulfillment is `DELIVERED` — or
        `PARTIALLY_DELIVERED` after the vessel has departed — and its payment
        dimension is still `UNINVOICED`, a `FinanceController` issues the invoice
        (any other combination is `ERR_ORDER_NOT_INVOICABLE`)." Issuing while
        fulfillment is still OPEN fails.

        Design: Corner/errors/error_order_not_invoicable_before_delivery
        """
        item_kw, lot_kw = _water("WATER-C22", "DS-C22")
        ctx = setup_accepted_order(qty=10, unit_price_cents=120,
                                   item_overrides=item_kw, lot_overrides=lot_kw)
        resp = api_client.create_invoice(
            ctx["order"]["id"], {"fx_rate_to_settlement": 1.0}, FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_INVOICABLE)


class TestErrorComplaintQtyExceedsDelivered:
    def test_error_complaint_qty_exceeds_delivered(self, api):
        """PRD §3.12: "No line may reject more of an item than that delivery
        actually delivered, else `ERR_QTY_EXCEEDS_REMAINING`." Rejecting 11
        units when 10 were delivered on that delivery fails.

        Design: Corner/errors/error_complaint_qty_exceeds_delivered
        """
        item_kw, lot_kw = _water("WATER-C27", "DS-AW")
        ctx = setup_delivered_order(qty=10, unit_price_cents=120,
                                    item_overrides=item_kw, lot_overrides=lot_kw)
        officer = make_officer_headers(ctx["call"]["id"])
        resp = api_client.create_complaint(ctx["delivery"]["id"], {
            "lines": [{"catalog_item_id": ctx["item"]["id"], "rejected_qty": 11,
                       "reason": "DAMAGED"}],
            "evidence_note": "claimed 11 of 10",
        }, officer)
        validate_error(resp, ApiErrorId.ERR_QTY_EXCEEDS_REMAINING)


# ===========================================================================
# rbac
# ===========================================================================

class TestSalesrepCannotCreateStockLot:
    def test_salesrep_cannot_create_stock_lot(self, api):
        """PRD §4: `POST /chandlery/stock-lots` is authorized for
        `WarehouseSupervisor` only. PRD §2.1: "If the named role is not
        permitted for the endpoint ... the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)." ChandlerSalesRep calling it
        fails 403.

        Design: Corner/rbac/salesrep_cannot_create_stock_lot
        """
        item = create_catalog_item(sku="RBAC-1", name="Item", category="DECK",
                                   base_price_cents=100)
        resp = api_client.create_stock_lot(
            {"catalog_item_id": item["id"], "lot_code": "X",
             "storage_tier": "DRY_STORE", "received_qty": 10, "capacity_qty": 0},
            SALES,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestOfficerCannotActForOtherVesselCall:
    def test_officer_cannot_act_for_other_vessel_call(self, api):
        """PRD §2.1: "When `X-User-Role` is `VesselCateringOfficer`, `X-User-ID`
        is the `id` of the acting `VesselCall`; ownership checks on any resource
        reachable from a vessel call — its requisitions, quotations, orders,
        deliveries, and complaints — compare the call's `id` to `X-User-ID`."
        An officer carrying vessel-call-B's id cannot submit a requisition
        belonging to vessel-call-A.

        Design: Corner/rbac/officer_cannot_act_for_other_vessel_call
        """
        agent = create_agent(name="Agent AV", credit_limit_cents=1000000)
        item = create_catalog_item(sku="RBAC-2", name="Item", category="DECK",
                                   base_price_cents=100)
        call_a = create_vessel_call(agent["id"], vessel_name="MV V-A")
        call_b = create_vessel_call(agent["id"], vessel_name="MV V-B")
        req = get_success_data(api_client.create_requisition(call_a["id"], {
            "title": "A's requisition", "lines": [{
                "catalog_item_id": item["id"], "requested_qty": 5,
                "allows_substitution": False,
            }],
        }, make_officer_headers(call_a["id"])))

        resp = api_client.submit_requisition(req["id"], make_officer_headers(call_b["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestClerkCannotPayOtherAgentsInvoice:
    def test_clerk_cannot_pay_other_agents_invoice(self, api):
        """PRD §2.1: "a clerk may record payments only against invoices billed to
        their own agent". PRD §3.10: "because the clerk's `X-User-ID` is the
        agent's `id`, a clerk may only pay invoices billed to their own agent
        (else `ERR_INSUFFICIENT_PERMISSIONS`)". A clerk carrying agent-2's id
        cannot pay an invoice billed to agent-1.

        Design: Corner/rbac/clerk_cannot_pay_other_agents_invoice
        """
        agent2 = create_agent(name="Agent W2")
        item_kw, lot_kw = _water("RBAC-3", "DS-W")
        ctx = setup_invoiced_order(
            qty=100, unit_price_cents=120, fx_rate_to_settlement=1.0,
            agent_overrides=dict(name="Agent W1"),
            item_overrides=item_kw, lot_overrides=lot_kw,
            call_overrides=dict(vessel_name="MV W-One"),
        )
        resp = api_client.create_payment(
            ctx["invoice"]["id"],
            {"amount_cents": 12000, "currency": "USD"},
            make_clerk_headers(agent2["id"]),  # wrong agent
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestWarehouseCannotConfirmDeliverySod:
    def test_warehouse_cannot_confirm_delivery_sod(self, api):
        """PRD §4: `POST /chandlery/deliveries/{id}/confirm` is authorized for
        `VesselCateringOfficer` only — "Receipt confirmation is the vessel's
        act" (§3.6). A WarehouseSupervisor calling confirm fails
        ERR_INSUFFICIENT_PERMISSIONS: the warehouse can never sign its own
        delivery.

        Design: Corner/rbac/warehouse_cannot_confirm_delivery_sod
        """
        item_kw, lot_kw = _water("RBAC-4", "DS-X")
        ctx = setup_accepted_order(qty=10, unit_price_cents=120,
                                   item_overrides=item_kw, lot_overrides=lot_kw)
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 10)
        dispatch_delivery(delivery["id"])
        resp = api_client.confirm_delivery(delivery["id"], {
            "receiver_name": "Warehouse Foreman", "signature_ref": "sig-x",
            "confirmed_lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 10}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


# ===========================================================================
# cross_cutting_layers: OCC
# ===========================================================================

class TestOccQuotationReviseStaleVersion:
    def test_occ_quotation_revise_stale_version(self, api):
        """PRD §2.6: "Revising a quotation requires the request to carry
        `expected_quotation_version` equal to the quotation's current `version`;
        ... if the parent entity's version has advanced beyond what the client
        last observed ... the write is rejected with `ERR_STALE_VERSION` (HTTP
        412)". Two sequential revises carrying the SAME observed version: the
        first succeeds (version advances), the second is rejected.

        Design: Corner/cross_cutting_layers/occ_quotation_revise_stale_version
        """
        agent = create_agent(name="Agent AY")
        water = create_catalog_item(
            sku="WATER-C23", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-Y", received_qty=10000)
        call = create_vessel_call(agent["id"], vessel_name="MV Yara")
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=100)
        quo = create_sent_quotation(req["id"], water["id"], qty=100, unit_price_cents=120)
        observed = get_success_data(api_client.get_quotation(quo["id"], SALES))
        v = observed["version"]

        first = get_success_data(api_client.revise_quotation(quo["id"], {
            "lines": [{"catalog_item_id": water["id"], "qty": 90,
                       "unit_price_cents": 115, "is_substitution": False}],
            "valid_until": "2026-08-12T00:00:00Z",
            "expected_quotation_version": v,
        }, SALES))
        assert first["version"] == v + 1, "First revise advances the version"

        resp = api_client.revise_quotation(quo["id"], {
            "lines": [{"catalog_item_id": water["id"], "qty": 80,
                       "unit_price_cents": 110, "is_substitution": False}],
            "valid_until": "2026-08-12T00:00:00Z",
            "expected_quotation_version": v,  # stale
        }, SALES)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestOccStockAdjustmentStaleVersion:
    def test_occ_stock_adjustment_stale_version(self, api):
        """PRD §2.6: "posting a cycle-count adjustment to a stock lot requires
        `expected_stock_lot_version` equal to the lot's current `version`" else
        `ERR_STALE_VERSION`. PRD §3.2: "A successful adjustment adds
        `adjustment_qty` to both `received_qty` and `on_hand_qty` while leaving
        `reserved_qty` untouched". A second adjustment carrying the stale
        version fails; on_hand reflects exactly one adjustment.

        Design: Corner/cross_cutting_layers/occ_stock_adjustment_stale_version
        """
        water = create_catalog_item(
            sku="WATER-C24", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        lot = create_stock_lot(water["id"], lot_code="DS-Z", received_qty=1000)
        v = lot["version"]

        adjusted = get_success_data(api_client.create_stock_adjustment(lot["id"], {
            "adjustment_qty": 50, "reason": "found pallet",
            "expected_stock_lot_version": v,
        }, WAREHOUSE))
        assert adjusted["on_hand_qty"] == 1050

        resp = api_client.create_stock_adjustment(lot["id"], {
            "adjustment_qty": -20, "reason": "damage writeoff",
            "expected_stock_lot_version": v,  # stale
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        lot_after = get_success_data(api_client.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["on_hand_qty"] == 1050, "Stale adjustment did not apply"


class TestImmediateConsistencyOnInvoiceIssuance:
    def test_immediate_consistency_on_invoice_issuance(self, api):
        """PRD §3.9: issuance "snapshots the agent's `settlement_currency` onto
        the invoice", stamps `issued_at` from the logical clock, computes
        `due_date` as `issued_at` plus the agent's `payment_terms_days`, and
        "The invoice opens as `ISSUED`". The create response itself already
        carries every computed field — no re-read is needed. Agent terms 7
        days, clock at ETA 2026-08-10T08:00:00Z: total 12,000, due
        2026-08-17T08:00:00Z.

        Design: Corner/cross_cutting_layers/immediate_consistency_on_invoice_issuance
        """
        item_kw, lot_kw = _water("WATER-C25", "DS-Z2")
        ctx = setup_delivered_order(
            qty=100, unit_price_cents=120,
            agent_overrides=dict(name="Agent AZ", payment_terms_days=7),
            item_overrides=item_kw, lot_overrides=lot_kw,
        )
        set_clock("2026-08-10T08:00:00Z")
        invoice = get_success_data(api_client.create_invoice(
            ctx["order"]["id"], {"fx_rate_to_settlement": 1.0}, FINANCE,
        ))
        assert invoice["total_cents"] == 12000
        assert invoice["status"] == "ISSUED"
        assert invoice["due_date"] == "2026-08-17T08:00:00Z", (
            f"issued at 2026-08-10T08:00:00Z clock + 7 days; got {invoice['due_date']}"
        )


# ===========================================================================
# consistency_model
# ===========================================================================

class TestOrderReadShowsPostConfirmStateImmediately:
    def test_order_read_shows_post_confirm_state_immediately(self, api):
        """PRD §3.6: "A successful confirm ... accumulates each confirmed quantity
        into the order line's `qty_delivered` ... and re-derives the order's
        fulfillment dimension: ... when every line's `qty_delivered` reaches its
        `qty_ordered` the order becomes `DELIVERED`." Immediately after the
        confirm response returns, GET /orders/{id} shows the cascaded state —
        no delay, no staleness.

        Design: Corner/consistency_model/order_read_shows_post_confirm_state_immediately
        """
        item_kw, lot_kw = _water("WATER-C26", "DS-BA")
        ctx = setup_accepted_order(qty=10, unit_price_cents=120,
                                   item_overrides=item_kw, lot_overrides=lot_kw)
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 10)
        dispatch_delivery(delivery["id"])
        officer = make_officer_headers(ctx["call"]["id"])
        confirm_delivery(delivery["id"], ctx["item"]["id"], 10, officer)

        order = get_success_data(api_client.get_order(ctx["order"]["id"], OPS))
        assert order["fulfillment_status"] == "DELIVERED"
        line = order["lines"][0]
        assert line["qty_delivered"] == 10
