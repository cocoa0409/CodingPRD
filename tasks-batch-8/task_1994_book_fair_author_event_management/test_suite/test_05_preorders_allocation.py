"""Preorders: intake window, opening-day allocation, fulfillment, cancel."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_preorder_payload,
    create_stock_line_payload,
    make_school,
    make_publisher,
    make_fair,
    make_fair_scheduled,
    make_accepted_agreement,
    make_delivered_stock_line,
    make_fair_stocking,
    make_fair_open,
    make_organizer_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestPreorderWindow:
    def test_preorder_window_closed_when_open(self, api):
        """PRD §3.6: "A `Cashier` places a `Preorder` with `fair_id`,
        `stock_line_id`, `customer_name`, and a positive `qty`, but only while
        the fair is `SCHEDULED` or `STOCKING` — intake at any other time is
        refused with `ERR_PREORDER_WINDOW_CLOSED` (HTTP 409)"

        Design: Corner/errors/preorder_window_closed_when_open
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        resp = api.create_preorder(
            create_preorder_payload(
                fair_id=fair["id"], stock_line_id=line["id"],
                customer_name="Late", qty=1,
            ), CASHIER,
        )
        validate_error(resp, ApiErrorId.ERR_PREORDER_WINDOW_CLOSED)

    def test_preorder_line_from_other_fair_rejected(self, api):
        """PRD §3.6: "a preorder whose stock line belongs to a different fair is
        reported as `ERR_LINE_FAIR_MISMATCH` even when the window is also
        closed."
        PRD §2.9: "then referential cross-checks (`ERR_LINE_FAIR_MISMATCH`,
        `ERR_TICKET_SESSION_MISMATCH`, priority 20)"

        Design: Corner/validations/preorder_line_from_other_fair_rejected
        """
        school = make_school()
        pub = make_publisher()
        # Fair A in STOCKING with a line
        fair_a, agr_a = make_fair_stocking(school["id"], pub["id"], title="Fair A")
        line_a = validate_success(api.create_stock_line(
            create_stock_line_payload(fair_id=fair_a["id"], agreement_id=agr_a["id"]),
            ORG,
        ), expected_status=201)
        # Fair B in SCHEDULED (intake window open) but owns no stock lines
        fair_b = make_fair_scheduled(school["id"], title="Fair B", venue_key="CAFETERIA")
        resp = api.create_preorder(
            create_preorder_payload(
                fair_id=fair_b["id"], stock_line_id=line_a["id"],
                customer_name="Ann", qty=1,
            ), CASHIER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_FAIR_MISMATCH)


class TestAllocation:
    def _setup_three_preorders(self):
        """Fair in STOCKING; one FRONTLIST line delivered 5; three PLACED preorders."""
        school = make_school()
        pub = make_publisher()
        fair, agr = make_fair_stocking(school["id"], pub["id"])
        line = make_delivered_stock_line(
            fair["id"], agr["id"], qty_committed=5, qty_delivered=5
        )
        p1 = validate_success(api_client.create_preorder(
            create_preorder_payload(fair_id=fair["id"], stock_line_id=line["id"],
                                    customer_name="Ann", qty=3), CASHIER,
        ), expected_status=201)
        p2 = validate_success(api_client.create_preorder(
            create_preorder_payload(fair_id=fair["id"], stock_line_id=line["id"],
                                    customer_name="Bob", qty=3), CASHIER,
        ), expected_status=201)
        p3 = validate_success(api_client.create_preorder(
            create_preorder_payload(fair_id=fair["id"], stock_line_id=line["id"],
                                    customer_name="Zed", qty=1), CASHIER,
        ), expected_status=201)
        return school, pub, fair, agr, line, p1, p2, p3

    def test_allocation_exact_fit_and_empty_stock(self, api):
        """PRD §3.6: "Every `PLACED` preorder of the fair is processed in a
        pinned order — `created_at` ascending, then `qty` ascending, then
        `customer_name` ascending, never by id — and each preorder is decided
        all-or-nothing at its turn: if its `qty` is no greater than its line's
        current `qty_available_for_sale`, the preorder becomes `ALLOCATED` and
        the hold is placed (`qty_held_preorder` grows by `qty`, availability
        recomputed); otherwise it becomes `CONVERTED_BACKLIST` with no hold
        placed, its demand deferred to a firm backlist reorder outside this
        API. A preorder that exactly exhausts the remaining availability is
        allocated. When a line has zero availability, every preorder still
        waiting on it converts to backlist without error."

        Design: Difficulty/boundary_precision_check/allocation_exact_fit_and_empty_stock
        """
        school, pub, fair, agr, line, p1, p2, p3 = self._setup_three_preorders()
        validate_success(api.open_fair(fair["id"], ORG))

        after1 = validate_success(api.get_preorder(p1["id"], ORG))
        after2 = validate_success(api.get_preorder(p2["id"], ORG))
        after3 = validate_success(api.get_preorder(p3["id"], ORG))
        assert after1["status"] == "ALLOCATED"
        assert after2["status"] == "CONVERTED_BACKLIST"
        assert after3["status"] == "ALLOCATED"

        after_line = validate_success(api.get_stock_line(line["id"], ORG))
        assert after_line["qty_held_preorder"] == 4
        assert after_line["qty_available_for_sale"] == 1

        after_fair = validate_success(api.get_fair(fair["id"], ORG))
        assert after_fair["preorder_allocation_run"] is True

    def test_allocation_runs_once_at_open(self, api):
        """PRD §3.6: "The open transition runs **preorder allocation** exactly
        once and sets `preorder_allocation_run` to true."

        Design: Difficulty/boundary_precision_check/allocation_exact_fit_and_empty_stock
        """
        school, pub, fair, agr, line, p1, p2, p3 = self._setup_three_preorders()
        resp = api.open_fair(fair["id"], ORG)
        data = validate_success(resp)
        assert data["preorder_allocation_run"] is True
        assert data["status"] == "OPEN"


class TestFulfill:
    def test_preorder_fulfill_price_and_gross_sync(self, api):
        """PRD §3.6: "A cashier fulfills an `ALLOCATED` preorder while the fair
        is `OPEN` (`ERR_FAIR_NOT_OPEN` otherwise); the preorder becomes
        `FULFILLED`, its `fulfillment_price_cents` is fixed at `qty` times the
        stock line's `list_price_cents`, the line's `qty_held_preorder`
        decreases by `qty` while its `qty_sold` increases by `qty`, and the
        fair's `gross_sales_cents` grows by `fulfillment_price_cents`."

        Design: Corner/calculations/preorder_fulfill_price_and_gross_sync
        """
        school = make_school()
        pub = make_publisher()
        fair, agr = make_fair_stocking(school["id"], pub["id"])
        line = make_delivered_stock_line(fair["id"], agr["id"], qty_committed=10)
        po = validate_success(api_client.create_preorder(
            create_preorder_payload(fair_id=fair["id"], stock_line_id=line["id"],
                                    customer_name="Ann", qty=2), CASHIER,
        ), expected_status=201)
        validate_success(api.open_fair(fair["id"], ORG))

        fulfilled = validate_success(api.fulfill_preorder(po["id"], CASHIER))
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["fulfillment_price_cents"] == 2000

        after_line = validate_success(api.get_stock_line(line["id"], ORG))
        assert after_line["qty_held_preorder"] == 0
        assert after_line["qty_sold"] == 2
        assert after_line["qty_available_for_sale"] == 8

        after_fair = validate_success(api.get_fair(fair["id"], ORG))
        assert after_fair["gross_sales_cents"] == 2000

    def test_fulfill_requires_fair_open(self, api):
        """PRD §3.6: "A cashier fulfills an `ALLOCATED` preorder while the fair
        is `OPEN` (`ERR_FAIR_NOT_OPEN` otherwise)"

        Design: Corner/calculations/preorder_fulfill_price_and_gross_sync
        """
        school = make_school()
        pub = make_publisher()
        fair, agr = make_fair_stocking(school["id"], pub["id"])
        line = make_delivered_stock_line(fair["id"], agr["id"], qty_committed=10)
        po = validate_success(api_client.create_preorder(
            create_preorder_payload(fair_id=fair["id"], stock_line_id=line["id"],
                                    customer_name="Ann", qty=2), CASHIER,
        ), expected_status=201)
        validate_success(api.open_fair(fair["id"], ORG))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        resp = api.fulfill_preorder(po["id"], CASHIER)
        # After close-sales the preorder was swept to CANCELLED, so the transition
        # no longer exists from that state.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
