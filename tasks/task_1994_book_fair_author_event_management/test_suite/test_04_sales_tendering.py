"""Register sales: tender, void, markdown band, stock availability, priority pairs."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    assert_copy_conservation,
    create_sale_payload,
    create_preorder_payload,
    make_school,
    make_publisher,
    make_fair_open,
    make_organizer_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def _open_fair_with_line(qty=10, list_price=1000, markdown=0.20):
    school = make_school()
    pub = make_publisher()
    fair, agr, lines = make_fair_open(
        school["id"], pub["id"],
        line_specs=[{"qty_committed": qty, "qty_delivered": qty,
                     "list_price_cents": list_price}],
    )
    return school, pub, fair, agr, lines[0]


class TestTenderStateVsFiscal:
    def test_tender_state_beats_fiscal(self, api):
        """PRD §3.6: "The `DRAFT` → `TENDERED` step first requires the sale's
        fair to be `OPEN` (`ERR_FAIR_NOT_OPEN`) before any fiscal check is
        evaluated; ... and finally the payload `tendered_amount_cents` must be
        at least the sale's `total_cents` (`ERR_TENDER_SHORT`, HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/tender_state_beats_fiscal
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        # Fair OPEN -> RECONCILING
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        # Tender with short amount: state gate fires first
        resp = api.tender_sale(sale["id"], {"tendered_amount_cents": 1}, CASHIER)
        validate_error(resp, ApiErrorId.ERR_FAIR_NOT_OPEN)
        # The error is 409 (state), not 402 (fiscal)
        assert resp.status_code == 409
        after = validate_success(api.get_sale(sale["id"], ORG))
        assert after["status"] == "DRAFT"

    def test_tender_state_beats_fiscal_http_status_not_402(self, api):
        """PRD §3.6: "The `DRAFT` → `TENDERED` step first requires the sale's
        fair to be `OPEN` (`ERR_FAIR_NOT_OPEN`) before any fiscal check is
        evaluated; ... and finally the payload `tendered_amount_cents` must be
        at least the sale's `total_cents` (`ERR_TENDER_SHORT`, HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/tender_state_beats_fiscal
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        resp = api.tender_sale(sale["id"], {"tendered_amount_cents": 1}, CASHIER)
        # The response is the 409 state error, never the 402 fiscal error.
        assert resp.status_code == 409
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_FAIR_NOT_OPEN"

    def test_sale_tender_requires_fair_open(self, api):
        """PRD §3.6: "The `DRAFT` → `TENDERED` step first requires the sale's
        fair to be `OPEN` (`ERR_FAIR_NOT_OPEN`) before any fiscal check is
        evaluated"

        Design: Difficulty/cross_entity_state_dependency/sale_tender_requires_fair_open
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        # Exact tender (no fiscal violation possible)
        resp = api.tender_sale(sale["id"], {"tendered_amount_cents": 1000}, CASHIER)
        validate_error(resp, ApiErrorId.ERR_FAIR_NOT_OPEN)
        after_sale = validate_success(api.get_sale(sale["id"], ORG))
        assert after_sale["status"] == "DRAFT"
        after_fair = validate_success(api.get_fair(fair["id"], ORG))
        assert after_fair["gross_sales_cents"] == 0

    def test_sale_tender_succeeds_while_fair_open(self, api):
        """PRD §3.6: "The `DRAFT` → `TENDERED` step first requires the sale's
        fair to be `OPEN` (`ERR_FAIR_NOT_OPEN`) ... On success each line's
        `qty_sold` grows by its `qty` with availability recomputed, the fair's
        `gross_sales_cents` grows by `total_cents`"

        Design: Difficulty/cross_entity_state_dependency/sale_tender_requires_fair_open
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        ok = validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 1000}, CASHIER))
        assert ok["status"] == "TENDERED"
        fair_after = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_after["gross_sales_cents"] == 1000


class TestTenderFiscal:
    def test_tender_short_clean_leg(self, api):
        """PRD §3.6: "finally the payload `tendered_amount_cents` must be at
        least the sale's `total_cents` (`ERR_TENDER_SHORT`, HTTP 402)."
        PRD §3.6: "the fair's `gross_sales_cents` grows by `total_cents` — a
        derived-field sync that bumps the fair's `version` — and
        `tendered_amount_cents` and `change_cents` (the tendered amount minus
        the total) are recorded."

        Design: Corner/errors/tender_short_clean_leg
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        resp_short = api.tender_sale(sale["id"], {"tendered_amount_cents": 999}, CASHIER)
        validate_error(resp_short, ApiErrorId.ERR_TENDER_SHORT)
        assert resp_short.status_code == 402

        resp_ok = api.tender_sale(sale["id"], {"tendered_amount_cents": 1000}, CASHIER)
        data = validate_success(resp_ok)
        assert data["status"] == "TENDERED"
        assert data["change_cents"] == 0

    def test_stock_not_available_at_tender(self, api):
        """PRD §3.6: "then each line's `qty` must fit within that line's
        `qty_available_for_sale` (`ERR_STOCK_NOT_AVAILABLE`, HTTP 409)"

        Design: Corner/errors/stock_not_available_at_tender
        """
        school, pub, fair, agr, line = _open_fair_with_line(qty=10)
        # Place + allocate preorder of qty 4 during STOCKING. Rebuild a fair where
        # the preorder is placed BEFORE the open transition.
        # Simpler: make a fresh fair with allocation path.
        # We rely on the fixture path: create a preorder in STOCKING then open.
        # (Re-do setup cleanly to control allocation.)
        # This test instead verifies availability at tender via direct sale.
        # Delivered 10, no holds: tender qty 11 fails.
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 11}]),
            CASHIER,
        ), expected_status=201)
        resp = api.tender_sale(sale["id"], {"tendered_amount_cents": 11000}, CASHIER)
        validate_error(resp, ApiErrorId.ERR_STOCK_NOT_AVAILABLE)
        after = validate_success(api.get_sale(sale["id"], ORG))
        assert after["status"] == "DRAFT"


class TestMarkdownBand:
    def test_markdown_price_floor_boundary(self, api):
        """PRD §3.6: "Both at creation and again at tender, any supplied
        `unit_price_cents` must sit inside the markdown band of the fair's
        `ACCEPTED` agreement: at least the floor of the list price scaled by one
        minus `markdown_allowance_pct`, and at most the list price itself
        (`ERR_PRICE_BEYOND_MARKDOWN`, HTTP 409)."

        Design: Corner/errors/markdown_price_floor_boundary
        """
        school, pub, fair, agr, line = _open_fair_with_line(list_price=1000, markdown=0.20)
        # Floor = floor(1000 * (1 - 0.20)) = 800
        resp_bad = api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1,
                                        "unit_price_cents": 799}]),
            CASHIER,
        )
        validate_error(resp_bad, ApiErrorId.ERR_PRICE_BEYOND_MARKDOWN)

        resp_ok = api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1,
                                        "unit_price_cents": 800}]),
            CASHIER,
        )
        data = validate_success(resp_ok, expected_status=201)
        assert data["total_cents"] == 800

    def test_markdown_above_list_rejected(self, api):
        """PRD §3.6: "any supplied `unit_price_cents` must sit inside the
        markdown band of the fair's `ACCEPTED` agreement: at least the floor of
        the list price scaled by one minus `markdown_allowance_pct`, and at most
        the list price itself (`ERR_PRICE_BEYOND_MARKDOWN`, HTTP 409)."

        Design: Corner/errors/markdown_price_floor_boundary
        """
        school, pub, fair, agr, line = _open_fair_with_line(list_price=1000)
        resp = api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1,
                                        "unit_price_cents": 1001}]),
            CASHIER,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_BEYOND_MARKDOWN)


class TestVoid:
    def test_sale_void_from_draft_no_compensation(self, api):
        """PRD §3.6: "Voiding a `DRAFT` sale compensates nothing, because
        nothing was ever committed."

        Design: Corner/state_machines/sale_void_from_draft_no_compensation
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 3}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.void_sale(sale["id"], CASHIER))
        after_sale = validate_success(api.get_sale(sale["id"], ORG))
        assert after_sale["status"] == "VOIDED"
        after_line = validate_success(api.get_stock_line(line["id"], ORG))
        assert after_line["qty_sold"] == 0
        assert after_line["qty_available_for_sale"] == 10
        after_fair = validate_success(api.get_fair(fair["id"], ORG))
        assert after_fair["gross_sales_cents"] == 0

    def test_sale_tender_void_copy_conservation(self, api):
        """PRD §3.3: "At all times after delivery, a line's `qty_delivered`
        equals the sum of `qty_held_preorder`, `qty_sold`, `qty_damaged`,
        `qty_returned_shipped`, and `qty_available_for_sale`"
        PRD §3.6: "Voiding a `TENDERED` sale fully compensates: each line's
        `qty_sold` decreases by its `qty`, availability is recomputed, and the
        fair's `gross_sales_cents` decreases by `total_cents`."

        Design: Difficulty/compensating_invariant/sale_tender_void_copy_conservation
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 3}]),
            CASHIER,
        ), expected_status=201)
        tendered = validate_success(api.tender_sale(
            sale["id"], {"tendered_amount_cents": 3000}, CASHIER
        ))
        assert tendered["total_cents"] == 3000
        assert tendered["change_cents"] == 0

        line_after_tender = validate_success(api.get_stock_line(line["id"], ORG))
        assert line_after_tender["qty_sold"] == 3
        assert line_after_tender["qty_available_for_sale"] == 7
        assert_copy_conservation(line_after_tender)

        validate_success(api.void_sale(sale["id"], CASHIER))
        line_after_void = validate_success(api.get_stock_line(line["id"], ORG))
        assert line_after_void["qty_sold"] == 0
        assert line_after_void["qty_available_for_sale"] == 10
        assert_copy_conservation(line_after_void)
        fair_after_void = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_after_void["gross_sales_cents"] == 0
        sale_after_void = validate_success(api.get_sale(sale["id"], ORG))
        assert sale_after_void["status"] == "VOIDED"

    def test_void_after_close_sales_rejected(self, api):
        """PRD §3.6: "From `DRAFT` or `TENDERED`, a cashier may void the sale
        while the fair is still `OPEN`; voids after close-sales are refused
        outright to protect reconciliation integrity."

        Design: Difficulty/compensating_invariant/sale_tender_void_copy_conservation
        """
        school, pub, fair, agr, line = _open_fair_with_line()
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 1000}, CASHIER))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        resp = api.void_sale(sale["id"], CASHIER)
        # Refused outright: fair is no longer OPEN, so the void transition is not offered
        validate_error(resp, ApiErrorId.ERR_FAIR_NOT_OPEN)
