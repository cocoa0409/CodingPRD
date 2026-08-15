"""Validation corner cases (corner-design §validations).

Auth header shape, existence-before-state, quantity floors, delivery caps,
substitution admissibility and price cap, duplicate SKU, FX-rate positivity,
and lazy quotation expiry.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    OPS,
    TEST_USERS,
    api_client,
    get_success_data,
    make_officer_headers,
    setup_accepted_order,
    validate_error,
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
    set_clock,
)

SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


def _water_ctx(qty=100, sku="WATER-C15", lot_code="DS-C15"):
    return setup_accepted_order(
        qty=qty, unit_price_cents=120,
        item_overrides=dict(sku=sku, name="Water 1L", category="PROVISIONS",
                            bonded_eligible=False, requires_cold_chain=False,
                            base_price_cents=120, duty_rate_pct=0),
        lot_overrides=dict(lot_code=lot_code, received_qty=10000),
    )


class TestMissingAuthHeadersReturns400:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or empty, the request is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        The auth check fires before any other check — even on a nonexistent
        resource id.

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        resp = api_client.get_vessel_call(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestExistenceBeatsStateOnUnknownQuotationAccept:
    def test_existence_beats_state_on_unknown_quotation_accept(self, api):
        """PRD §4: `POST /chandlery/quotations/{id}/accept`. Accept on a
        nonexistent quotation id returns ERR_QUOTATION_NOT_FOUND (404 per
        PRD §5), never a state error — existence is checked before state.

        Design: Corner/validations/existence_beats_state_on_unknown_quotation_accept
        """
        resp = api_client.accept_quotation(
            NON_EXISTENT_UUID, make_officer_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTATION_NOT_FOUND)


class TestDeliveryLineZeroQtyRejected:
    def test_delivery_line_zero_qty_rejected(self, api):
        """PRD §3.6: "a `lines` array of `{catalog_item_id, qty}` with each `qty`
        at least 1" — a planned line qty of 0 fails ERR_INVALID_QTY (zero is
        only legal at confirm time, where each confirmed qty is "at least zero"
        per the confirm payload).

        Design: Corner/validations/delivery_line_zero_qty_rejected
        """
        ctx = _water_ctx(100, "WATER-C15", "DS-C15")
        resp = api_client.create_delivery(ctx["order"]["id"], {
            "window_start": "2026-08-10T10:00:00Z",
            "window_end": "2026-08-10T14:00:00Z",
            "lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 0}],
        }, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_QTY)


class TestConfirmQtyExceedsPlannedRejected:
    def test_confirm_qty_exceeds_planned_rejected(self, api):
        """PRD §3.6: "the `confirmed_lines` array giving the actual received `qty`
        per item — each at least zero and at most the planned quantity on this
        delivery, else `ERR_QTY_EXCEEDS_REMAINING`." Confirming 101 against a
        plan of 100 fails.

        Design: Corner/validations/confirm_qty_exceeds_planned_rejected
        """
        ctx = _water_ctx(100, "WATER-C16", "DS-C16")
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 100)
        dispatch_delivery(delivery["id"])
        officer = make_officer_headers(ctx["call"]["id"])
        resp = api_client.confirm_delivery(delivery["id"], {
            "receiver_name": "Cook", "signature_ref": "sig-c16",
            "confirmed_lines": [{"catalog_item_id": ctx["item"]["id"], "qty": 101}],
        }, officer)
        validate_error(resp, ApiErrorId.ERR_QTY_EXCEEDS_REMAINING)


class TestSubstitutionDisallowedByRequisitionLine:
    def test_substitution_disallowed_by_requisition_line(self, api):
        """PRD §3.14: "the original requisition line must have
        `allows_substitution` true ... A violation is
        `ERR_SUBSTITUTION_NOT_ALLOWED`." Quoting a substitute when the
        requisition line has allows_substitution == false fails even if the
        substitute is cheaper and in stock.

        Design: Corner/validations/substitution_disallowed_by_requisition_line
        """
        agent = create_agent(name="Agent AP")
        water_a = create_catalog_item(
            sku="WATER-A17", name="Water Brand A", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        water_b = create_catalog_item(
            sku="WATER-B17", name="Water Brand B", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=100, duty_rate_pct=0,
        )
        create_stock_lot(water_b["id"], lot_code="DS-C17", received_qty=10000)
        call = create_vessel_call(agent["id"], vessel_name="MV Pallas")
        req = create_submitted_requisition(call["id"], water_a["id"], requested_qty=100,
                                           allows_substitution=False)
        resp = api_client.create_quotation(req["id"], {
            "lines": [{
                "catalog_item_id": water_b["id"], "qty": 100, "unit_price_cents": 100,
                "is_substitution": True, "substitution_of_item_id": water_a["id"],
            }],
            "valid_until": "2026-08-12T00:00:00Z",
        }, SALES)
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED)


class TestSubstitutionPriceCapBoundary:
    def _setup_oil_requisition(self, agent, oil, title):
        call = create_vessel_call(agent["id"], vessel_name="MV Qanitt")
        req = create_submitted_requisition(call["id"], oil["id"], requested_qty=10,
                                           allows_substitution=True)
        return req

    def test_substitution_price_cap_boundary(self, api):
        """PRD §3.14: "its `unit_price_cents` must not exceed the original item's
        `base_price_cents` multiplied by 115 and divided by 100, rounded
        half-up. The boundary is inclusive — a substitute priced exactly at the
        cap passes — and anything above is
        `ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED`." Original base 400 => cap 460:
        460 passes, 461 fails.

        Design: Corner/validations/substitution_price_cap_boundary
        """
        agent = create_agent(name="Agent AQ")
        oil = create_catalog_item(
            sku="OIL-C18", name="Olive Oil 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=400, duty_rate_pct=0,
        )
        oil_prem = create_catalog_item(
            sku="OILP-C18", name="Olive Oil Premium 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=900, duty_rate_pct=0,
        )
        create_stock_lot(oil_prem["id"], lot_code="DS-C18", received_qty=1000)
        req_ok = self._setup_oil_requisition(agent, oil, "Oil ok")
        req_bad = self._setup_oil_requisition(agent, oil, "Oil bad")

        resp_ok = api_client.create_quotation(req_ok["id"], {
            "lines": [{
                "catalog_item_id": oil_prem["id"], "qty": 10, "unit_price_cents": 460,
                "is_substitution": True, "substitution_of_item_id": oil["id"],
            }],
            "valid_until": "2026-08-12T00:00:00Z",
        }, SALES)
        quo_ok = validate_success(resp_ok, expected_status=201)
        assert quo_ok["provisional_total_cents"] == 4600, "460 == cap: accepted"

        resp_bad = api_client.create_quotation(req_bad["id"], {
            "lines": [{
                "catalog_item_id": oil_prem["id"], "qty": 10, "unit_price_cents": 461,
                "is_substitution": True, "substitution_of_item_id": oil["id"],
            }],
            "valid_until": "2026-08-12T00:00:00Z",
        }, SALES)
        validate_error(resp_bad, ApiErrorId.ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED)


class TestDuplicateSkuRejected:
    def test_duplicate_sku_rejected(self, api):
        """PRD §3.1: "a `sku` that must be unique across the entire catalog
        (duplicates are rejected `ERR_DUPLICATE_SKU`)". A second catalog item
        with an existing sku fails ERR_DUPLICATE_SKU (409).

        Design: Corner/validations/duplicate_sku_rejected
        """
        create_catalog_item(sku="DUP-1", name="First", category="DECK",
                            base_price_cents=100)
        resp = api_client.create_catalog_item(
            {"sku": "DUP-1", "name": "Second", "category": "CABIN",
             "bonded_eligible": False, "requires_cold_chain": False,
             "base_price_cents": 200, "duty_rate_pct": 0},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)


class TestInvoiceFxRateZeroRejected:
    def test_invoice_fx_rate_zero_rejected(self, api):
        """PRD §3.9: "Issuance carries a single input, `fx_rate_to_settlement` —
        the USD-to-settlement-currency conversion rate, which must be strictly
        positive, else `ERR_INVALID_FX_RATE`". fx_rate_to_settlement == 0 fails
        even on an otherwise invoicable order.

        Design: Corner/validations/invoice_fx_rate_zero_rejected
        """
        from test_helpers import setup_delivered_order
        ctx = setup_delivered_order(
            qty=100, unit_price_cents=120,
            item_overrides=dict(sku="WATER-C19", name="Water 1L"),
            lot_overrides=dict(lot_code="DS-C19", received_qty=10000),
        )
        resp = api_client.create_invoice(
            ctx["order"]["id"], {"fx_rate_to_settlement": 0}, TEST_USERS["finance_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FX_RATE)


class TestQuotationLazyExpiryOnAccept:
    def _sent_quotation(self, agent, water, vessel_name, imo_number):
        call = create_vessel_call(agent["id"], vessel_name=vessel_name, imo_number=imo_number)
        officer = make_officer_headers(call["id"])
        req = create_submitted_requisition(call["id"], water["id"], requested_qty=10)
        quo = create_sent_quotation(
            req["id"], water["id"], qty=10, unit_price_cents=120,
            valid_until="2026-08-11T00:00:00Z",
        )
        return call, officer, quo

    def test_accept_at_exactly_valid_until_succeeds(self, api):
        """PRD §3.4: "The deadline is inclusive — acceptance at exactly
        `valid_until` is valid." Quotation valid_until 2026-08-11T00:00:00Z,
        vessel IN_PORT; clock advanced to exactly valid_until: accept succeeds.

        Design: Corner/validations/quotation_lazy_expiry_on_accept
        """
        agent = create_agent(name="Agent AS")
        water = create_catalog_item(
            sku="WATER-C20", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-C20", received_qty=10000)
        call, officer, quo = self._sent_quotation(agent, water, "MV Selkie", "9074781")
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])
        set_clock("2026-08-11T00:00:00Z")  # exactly valid_until
        order = get_success_data(api_client.accept_quotation(quo["id"], officer))
        assert order["fulfillment_status"] == "OPEN", (
            "Accept at exactly valid_until succeeds (inclusive boundary)"
        )

    def test_accept_one_second_after_valid_until_expires_lazily(self, api):
        """PRD §3.4: "any send, revise, or accept attempt made when the logical
        clock reads strictly after `valid_until` flips the quotation to `EXPIRED`
        and fails with `ERR_QUOTATION_EXPIRED`." Accept at valid_until + 1s fails
        and the quotation is EXPIRED on a subsequent GET (lazy materialization).

        Design: Corner/validations/quotation_lazy_expiry_on_accept
        """
        agent = create_agent(name="Agent AS")
        water = create_catalog_item(
            sku="WATER-C20", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        create_stock_lot(water["id"], lot_code="DS-C20", received_qty=10000)
        call, officer, quo = self._sent_quotation(agent, water, "MV Siren", "9074782")
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])
        set_clock("2026-08-11T00:00:01Z")  # one second past valid_until
        resp = api_client.accept_quotation(quo["id"], officer)
        validate_error(resp, ApiErrorId.ERR_QUOTATION_EXPIRED)
        quotation = get_success_data(api_client.get_quotation(quo["id"], SALES))
        assert quotation["status"] == "EXPIRED", (
            "The failed accept lazily flips the quotation to EXPIRED"
        )
