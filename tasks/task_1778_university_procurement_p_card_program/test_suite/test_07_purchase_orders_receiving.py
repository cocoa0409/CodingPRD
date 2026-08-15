"""Purchase orders: issuance gate, parallel status axes, cancel, receipts."""
from test_helpers import (
    ApiErrorId,
    assert_purchase_order,
    create_and_submit_requisition,
    create_department,
    create_po,
    create_vendor,
    get_success_data,
    issue_po_ok,
    post_invoice,
    post_receipt,
    requisition_line,
    validate_error,
    walk_approval_chain,
)
from test_helpers.fixtures import ADMIN, AP_CLERK, BUYER, DEPT_APPROVER, RECEIVING

ADMIN_H = ADMIN
BUYER_H = BUYER
DEPT_H = DEPT_APPROVER
AP_H = AP_CLERK


class TestIssuePoGate:
    def _submitted_req(self):
        dept = create_department(name="Sociology")
        vendor = create_vendor(legal_name="SurveyCo")
        return create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="SOC", description="panel",
                unit_price_cents=400000, cost_category="SERVICES",
            )],
        )

    def test_issue_po_rejected_while_submitted(self, api):
        """PRD §3.5: "Issuance from any other status is rejected with
        `ERR_REQUISITION_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/issue_po_requires_approved_requisition
        """
        req = self._submitted_req()
        resp = api.issue_po(req["id"], BUYER_H)
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_APPROVED, 409)
        live = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert live["status"] == "SUBMITTED"

    def test_issue_po_succeeds_after_chain_completes(self, api):
        """PRD §3.5: "The requisition advances to `PO_ISSUED`, a terminal status
        for it, while the grant encumbrance itself is unchanged — conceptually
        the encumbrance simply transfers from the approved requisition to the
        now-outstanding purchase order."

        Design: Difficulty/cross_entity_state_dependency/issue_po_requires_approved_requisition
        """
        req = self._submitted_req()
        blocked = api.issue_po(req["id"], BUYER_H)
        validate_error(blocked, ApiErrorId.ERR_REQUISITION_NOT_APPROVED, 409)
        get_success_data(api.approve_requisition_step(req["id"], {}, DEPT_H))
        po = issue_po_ok(req["id"])
        assert_purchase_order(po)
        assert po["fulfillment_status"] == "ISSUED"
        assert po["requisition_id"] == req["id"]
        live = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert live["status"] == "PO_ISSUED"


class TestParallelDimensions:
    def _po_qty2(self):
        return create_po(lines=[requisition_line(
            commodity_code="THR", description="spots", quantity=2,
            unit_price_cents=300000, cost_category="EQUIPMENT",
        )])

    def test_fulfillment_and_match_axes_evolve_independently(self, api):
        """PRD §3.5: "Its `fulfillment_status` begins at `ISSUED` and is driven
        purely by receipts; its `match_status` is derived from invoices and
        cascades — `UNMATCHED` while no invoice exists, `EXCEPTION` while any
        invoice stands in `EXCEPTION` or the `contract_terminated_flag`
        (initially false) is set, `MATCHED` when at least one invoice is
        `PAYABLE` or `PAID` and none is in `EXCEPTION`, and `CLOSED` once the
        order is `CANCELLED`."
        PRD §3.5: "Receipts mutate only fulfillment; invoices and contract
        cascades mutate only match posture".

        Design: Difficulty/non_linear_state_machine/po_fulfillment_match_parallel_dimensions
        """
        po = self._po_qty2()
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        mid = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert mid["fulfillment_status"] == "PARTIALLY_RECEIVED"
        assert mid["match_status"] == "UNMATCHED"

        inv = post_invoice(
            po["id"], [{"line_no": 0, "quantity": 2, "unit_price_cents": 300000}],
            invoice_number="INV-P",
        )
        assert inv["status"] == "EXCEPTION"
        assert inv["exception_reason"] == "QTY_OVER_RECEIPT"
        after_invoice = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert after_invoice["fulfillment_status"] == "PARTIALLY_RECEIVED", (
            "invoices never touch the fulfillment axis"
        )
        assert after_invoice["match_status"] == "EXCEPTION"

        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        done = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert done["fulfillment_status"] == "FULLY_RECEIVED"
        assert done["match_status"] == "EXCEPTION", (
            "completing receiving does not clear the match axis"
        )

    def test_accept_variance_clears_match_without_touching_fulfillment(self, api):
        """PRD §3.6: "Accepting the variance re-runs the three-way match against
        the current `POSTED` receipts and pinned order prices; only if the
        re-match passes does the invoice move to `PAYABLE`, recording the resolver
        in `variance_accepted_by`".

        Design: Difficulty/non_linear_state_machine/po_fulfillment_match_parallel_dimensions
        """
        po = self._po_qty2()
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        inv = post_invoice(
            po["id"], [{"line_no": 0, "quantity": 2, "unit_price_cents": 300000}],
            invoice_number="INV-P",
        )
        assert inv["status"] == "EXCEPTION"
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])

        resolved = get_success_data(
            api.resolve_invoice_exception(
                inv["id"], {"action": "ACCEPT_VARIANCE"}, AP_H
            )
        )
        assert resolved["status"] == "PAYABLE"
        assert resolved["variance_accepted_by"] == "ap-1"
        final = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert final["match_status"] == "MATCHED"
        assert final["fulfillment_status"] == "FULLY_RECEIVED"


class TestPoCancelRoundTrip:
    def test_po_cancel_round_trip(self, api):
        """PRD §3.5: "Cancellation moves fulfillment to `CANCELLED` and match
        posture to `CLOSED`, releases the grant encumbrance by subtracting the
        order's `charge_cents` when it is grant-funded, and returns the source
        requisition from `PO_ISSUED` to `APPROVED` so that issuance can be
        attempted again."
        PRD §3.5: "An order may be cancelled by a buyer only while it is `ISSUED`
        with no `POSTED` receipts and no invoices at all — otherwise
        `ERR_PO_NOT_CANCELLABLE`."

        Design: Corner/endpoints/po_cancel_returns_requisition_to_approved
        """
        dept = create_department(name="RoundTrip")
        vendor = create_vendor(legal_name="RTCo")
        req = create_and_submit_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="RT", description="tools",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )
        walk_approval_chain(req["id"])
        po1 = issue_po_ok(req["id"])

        cancelled = get_success_data(api.cancel_purchase_order(po1["id"], BUYER_H))
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["match_status"] == "CLOSED"
        req_after = get_success_data(api.get_requisition(req["id"], ADMIN_H))
        assert req_after["status"] == "APPROVED"

        po2 = issue_po_ok(req["id"])  # re-issue succeeds
        post_receipt(po2["id"], [{"line_no": 0, "quantity": 1}])
        blocked = api.cancel_purchase_order(po2["id"], BUYER_H)
        validate_error(blocked, ApiErrorId.ERR_PO_NOT_CANCELLABLE, 409)


class TestReceiptVoidRematch:
    def test_receipt_void_rematches_payable_invoice(self, api):
        """PRD §3.5: "every invoice on the order still `PAYABLE` is re-matched,
        and if any line's invoiced quantity now exceeds the cumulative posted
        received quantity, that invoice drops to `EXCEPTION` with
        `exception_reason` `RECEIPT_VOIDED`."
        PRD §3.5: "voiding anything else is `ERR_RECEIPT_NOT_VOIDABLE`".

        Design: Corner/state_machines/receipt_void_rematches_payable_invoice
        """
        po = create_po(lines=[requisition_line(
            commodity_code="ZOO", description="cages", quantity=2,
            unit_price_cents=300000, cost_category="SUPPLIES",
        )])
        r1 = post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])
        inv = post_invoice(
            po["id"], [{"line_no": 0, "quantity": 2, "unit_price_cents": 300000}],
            invoice_number="INV-V",
        )
        assert inv["status"] == "PAYABLE"

        get_success_data(api.void_receipt(r1["id"], RECEIVING))
        po_after = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert po_after["fulfillment_status"] == "PARTIALLY_RECEIVED"
        assert po_after["match_status"] == "EXCEPTION"
        inv_after = get_success_data(api.get_invoice(inv["id"], ADMIN_H))
        assert inv_after["status"] == "EXCEPTION"
        assert inv_after["exception_reason"] == "RECEIPT_VOIDED"

        double_void = api.void_receipt(r1["id"], RECEIVING)
        validate_error(double_void, ApiErrorId.ERR_RECEIPT_NOT_VOIDABLE, 409)


class TestInvoiceLineAndOverReceipt:
    def test_invoice_unknown_line_and_over_receipt(self, api):
        """PRD §3.6: "Every `line_no` on the invoice must exist on the pinned
        order lines (otherwise `ERR_INVOICE_LINE_UNKNOWN`)".
        PRD §3.5: "Per line, the cumulative quantity across all `POSTED` receipts
        plus the new quantity may not exceed the ordered quantity, or the posting
        fails with `ERR_OVER_RECEIPT`."

        Design: Corner/validations/invoice_line_unknown_and_over_receipt
        """
        po = create_po(lines=[requisition_line(
            commodity_code="VET", description="scrubs", quantity=2,
            unit_price_cents=300000, cost_category="SUPPLIES",
        )])
        post_receipt(po["id"], [{"line_no": 0, "quantity": 1}])

        unknown = api.create_invoice(
            po["id"],
            {
                "invoice_number": "INV-X",
                "lines": [{"line_no": 9, "quantity": 1, "unit_price_cents": 300000}],
            },
            AP_H,
        )
        validate_error(unknown, ApiErrorId.ERR_INVOICE_LINE_UNKNOWN, 422)

        over = api.create_receipt(
            po["id"], {"lines": [{"line_no": 0, "quantity": 2}]}, RECEIVING
        )
        # cumulative 1 + 2 = 3 > ordered 2
        validate_error(over, ApiErrorId.ERR_OVER_RECEIPT, 422)

        live = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert live["fulfillment_status"] == "PARTIALLY_RECEIVED"
