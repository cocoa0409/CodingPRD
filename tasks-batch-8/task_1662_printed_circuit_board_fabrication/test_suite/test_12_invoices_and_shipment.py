"""Invoice lifecycle, shipment gates, and terminal-state lockdown (PRD §3.9)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_invoice,
    create_customer, create_order, prepare_order, setup_completed_order,
    setup_shipped_order, create_invoice_payload,
    make_customer_headers,
    TEST_USERS,
)

SALES = TEST_USERS["sales_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
FAB_ADMIN = TEST_USERS["fab_admin_headers"]


class TestInvoiceLifecycle:
    def test_invoice_lifecycle_draft_to_paid(self, api):
        """PRD §3.9: "it opens in `DRAFT`, a `SalesEngineer` issues it
        (`ISSUED`), and the billed `Customer` pays it (`PAID`)."

        Design: Corner/state_machines/invoice_lifecycle_draft_to_paid
        """
        ctx = setup_completed_order(
            company_name="Inv Co", contact_email="inv@co.example",
            lot_code="LOT-IV1",
        )
        invoice = get_success_data(
            api.create_final_invoice(
                ctx["order"]["id"], create_invoice_payload(), PLANNER,
            )
        )
        assert_invoice(invoice)
        assert invoice["status"] == "DRAFT"
        assert invoice["retest_fees_cents"] == 0, (
            "no retests occurred, so the FINAL retest line is zero (PRD §3.9)"
        )

        invoice = get_success_data(api.issue_invoice(invoice["id"], SALES))
        assert invoice["status"] == "ISSUED"

        invoice = get_success_data(
            api.pay_invoice(invoice["id"],
                            make_customer_headers(ctx["customer"]["id"]))
        )
        assert invoice["status"] == "PAID", "DRAFT -> ISSUED -> PAID closes"

    def test_invoice_pay_from_draft_rejected(self, api):
        """PRD §3.9: "it opens in `DRAFT`, a `SalesEngineer` issues it
        (`ISSUED`), and the billed `Customer` pays it (`PAID`)" — pay is defined
        only from ISSUED, so a DRAFT invoice hits PRD §2.9's "generic
        transition-legality guard (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/invoice_pay_from_draft_rejected
        """
        ctx = setup_completed_order(
            company_name="Draft Co", contact_email="draft@co.example",
            lot_code="LOT-DR1", spec_lines=(),
        )
        invoice = get_success_data(
            api.create_final_invoice(
                ctx["order"]["id"], create_invoice_payload(), PLANNER,
            )
        )
        assert invoice["status"] == "DRAFT"

        resp = api.pay_invoice(
            invoice["id"], make_customer_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        invoice = get_success_data(api.get_invoice(invoice["id"], PLANNER))
        assert invoice["status"] == "DRAFT"

    def test_invoice_exists_rejected(self, api):
        """PRD §3.9: "An order may carry at most one invoice; a second create is
        rejected with `ERR_INVOICE_EXISTS`, with the state guard ahead of it."

        Design: Corner/validations/invoice_exists_rejected
        """
        ctx = setup_completed_order(
            company_name="InvDup Co", contact_email="invdup@co.example",
            lot_code="LOT-ID1", spec_lines=(),
        )
        get_success_data(
            api.create_final_invoice(
                ctx["order"]["id"], create_invoice_payload(), PLANNER,
            )
        )
        resp = api.create_final_invoice(
            ctx["order"]["id"], create_invoice_payload(), PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS)


class TestShipment:
    def test_cancel_from_shipped_rejected(self, api):
        """PRD §3.9: cancellation is available "only while the order is in
        `QUOTED`, `DFM_REVIEW`, `AWAITING_LAMINATE`, `RELEASED`, or `ON_HOLD`;
        from `IN_PRODUCTION`, `AWAITING_ETEST`, `COMPLETED`, `SHIPPED`, or
        `CANCELLED` the attempt is rejected with `ERR_ORDER_NOT_CANCELLABLE`."
        Shipment itself: "A `ProductionPlanner` ships a `COMPLETED` order ... A
        passing ship moves the order to `SHIPPED`, closing the pipeline."

        Design: Corner/state_machines/cancel_from_shipped_rejected
        """
        ctx = setup_shipped_order(
            company_name="Term Co", contact_email="term@co.example",
            lot_code="LOT-SH1",
        )
        assert ctx["order"]["fab_status"] == "SHIPPED"

        resp = api.cancel_order(ctx["order"]["id"], {"reason": "too late"}, FAB_ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "SHIPPED"
