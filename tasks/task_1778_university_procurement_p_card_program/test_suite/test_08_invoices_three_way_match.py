"""Invoices: three-way match rounding, reason precedence, exception branches."""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    create_department,
    create_po,
    create_vendor,
    get_success_data,
    issue_po_ok,
    post_invoice,
    post_receipt,
    requisition_line,
    create_approved_requisition,
    validate_error,
)
from test_helpers.fixtures import ADMIN, AP_CLERK

ADMIN_H = ADMIN
AP_H = AP_CLERK


class TestPerLineRoundingOrder:
    def _po_three_lines(self):
        return create_po(lines=[
            requisition_line(
                commodity_code="ART", description="canvas", quantity=1,
                unit_price_cents=250, cost_category="SUPPLIES",
            ),
            requisition_line(
                commodity_code="ART", description="brushes", quantity=1,
                unit_price_cents=125, cost_category="SUPPLIES",
            ),
            requisition_line(
                commodity_code="ART", description="easels", quantity=1,
                unit_price_cents=125, cost_category="SUPPLIES",
            ),
        ])

    def test_per_line_tolerance_rounding_keeps_invoice_payable(self, api):
        """PRD §3.6: "the line's tolerance is two percent of the order line's
        `unit_price_cents` multiplied by the invoiced quantity, rounded half up to
        whole cents — each line's tolerance is rounded before any summation takes
        place." and "Even when no individual line fails, if the aggregate variance
        exceeds the aggregate tolerance the invoice is an `EXCEPTION` for price."

        Design: Difficulty/combinatorial_formula/three_way_match_per_line_rounding_order
        """
        po = self._po_three_lines()
        post_receipt(po["id"], [
            {"line_no": 0, "quantity": 1},
            {"line_no": 1, "quantity": 1},
            {"line_no": 2, "quantity": 1},
        ])
        inv = post_invoice(po["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 255},
            {"line_no": 1, "quantity": 1, "unit_price_cents": 128},
            {"line_no": 2, "quantity": 1, "unit_price_cents": 128},
        ], invoice_number="INV-R")
        # Per-line tolerances round half up BEFORE summing: 5, 3, 3 -> 11;
        # per-line variances are 5, 3, 3 -> 11; 11 <= 11 stays PAYABLE.
        assert inv["status"] == "PAYABLE", (
            f"per-line-then-sum tolerance 11 must absorb variance 11, got "
            f"{inv['status']} ({inv.get('exception_reason')})"
        )
        assert inv["total_variance_cents"] == 11
        assert inv["total_tolerance_cents"] == 11

    def test_clean_match_reason_none_and_po_matched(self, api):
        """PRD §3.6: "A clean invoice lands in `PAYABLE` with `exception_reason`
        `NONE`. Whichever way it lands, the order's match posture is recomputed."
        PRD §3.5: "`MATCHED` when at least one invoice is `PAYABLE` or `PAID` and
        none is in `EXCEPTION`".

        Design: Difficulty/combinatorial_formula/three_way_match_per_line_rounding_order
        """
        po = self._po_three_lines()
        post_receipt(po["id"], [
            {"line_no": 0, "quantity": 1},
            {"line_no": 1, "quantity": 1},
            {"line_no": 2, "quantity": 1},
        ])
        inv = post_invoice(po["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 255},
            {"line_no": 1, "quantity": 1, "unit_price_cents": 128},
            {"line_no": 2, "quantity": 1, "unit_price_cents": 128},
        ], invoice_number="INV-R")
        assert_invoice(inv)
        assert inv["exception_reason"] == "NONE"
        po_after = get_success_data(api.get_purchase_order(po["id"], ADMIN_H))
        assert po_after["match_status"] == "MATCHED"


class TestExceptionReasonPrecedence:
    def test_invoice_exception_reason_precedence(self, api):
        """PRD §3.6: "If the order has no `POSTED` receipts at all, the invoice is
        born in `EXCEPTION` with `exception_reason` `NO_RECEIPT` and evaluation
        stops there, leaving both totals at zero."
        PRD §3.6: "A single `exception_reason` is recorded by precedence:
        `NO_RECEIPT` first, then `QTY_OVER_RECEIPT`, then `PRICE_VARIANCE`; when
        several lines fail under the same reason, the lowest failing line number
        decides."

        Design: Corner/errors/invoice_exception_reason_precedence
        """
        dept = create_department(name="Prec")
        vendor = create_vendor(legal_name="PrecCo")
        r1 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[
                requisition_line(
                    commodity_code="PR", description="a", quantity=5,
                    unit_price_cents=1000, cost_category="SUPPLIES",
                ),
                requisition_line(
                    commodity_code="PR", description="b", quantity=5,
                    unit_price_cents=2000, cost_category="SUPPLIES",
                ),
            ],
        )
        po1 = issue_po_ok(r1["id"])
        post_receipt(po1["id"], [
            {"line_no": 0, "quantity": 5},
            {"line_no": 1, "quantity": 3},
        ])

        r2 = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="PR", description="c", quantity=1,
                unit_price_cents=5000, cost_category="SUPPLIES",
            )],
        )
        po2 = issue_po_ok(r2["id"])

        inv1 = post_invoice(po1["id"], [
            {"line_no": 0, "quantity": 6, "unit_price_cents": 1000},
            {"line_no": 1, "quantity": 3, "unit_price_cents": 2200},
        ], invoice_number="INV-P1")
        # Line 0 fails on quantity (6 > received 5); line 1 fails on price
        # (variance 600 > tolerance 120). QTY_OVER_RECEIPT outranks price, and
        # the lowest failing line decides.
        assert inv1["status"] == "EXCEPTION"
        assert inv1["exception_reason"] == "QTY_OVER_RECEIPT"

        inv2 = post_invoice(po2["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 5000},
        ], invoice_number="INV-P2")
        assert inv2["status"] == "EXCEPTION"
        assert inv2["exception_reason"] == "NO_RECEIPT"
        assert inv2["total_variance_cents"] == 0
        assert inv2["total_tolerance_cents"] == 0


class TestInvoiceExceptionBranches:
    def test_invoice_reject_reopens_and_paid_closes(self, api):
        """PRD §3.6: "Rejecting terminates the invoice as `REJECTED`, which
        reopens the order for a fresh invoice."
        PRD §3.6: "it must not already carry an open invoice in `PAYABLE` or
        `EXCEPTION`, nor a `PAID` one — invoicing is closed in either case with
        `ERR_PO_INVOICING_CLOSED`."

        Design: Corner/errors/invoice_reject_reopens_paid_closes_invoicing
        """
        dept = create_department(name="Branch")
        vendor = create_vendor(legal_name="BranchCo")

        # PO-A: invoice with a large price variance lands EXCEPTION.
        ra = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="BR", description="a", quantity=1,
                unit_price_cents=100000, cost_category="SUPPLIES",
            )],
        )
        poa = issue_po_ok(ra["id"])
        post_receipt(poa["id"], [{"line_no": 0, "quantity": 1}])
        inva = post_invoice(poa["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 130000},
        ], invoice_number="INV-A1")
        assert inva["status"] == "EXCEPTION"  # variance 30,000 > tolerance 2,000

        # PO-B: exact invoice, paid.
        rb = create_approved_requisition(
            department_id=dept["id"], vendor_id=vendor["id"],
            lines=[requisition_line(
                commodity_code="BR", description="b", quantity=1,
                unit_price_cents=100000, cost_category="SUPPLIES",
            )],
        )
        pob = issue_po_ok(rb["id"])
        post_receipt(pob["id"], [{"line_no": 0, "quantity": 1}])
        invb = post_invoice(pob["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 100000},
        ], invoice_number="INV-B1")
        get_success_data(api.pay_invoice(invb["id"], AP_H))

        rejected = get_success_data(
            api.resolve_invoice_exception(
                inva["id"],
                {"action": "REJECT_INVOICE", "comment": "supplier will reissue"},
                AP_H,
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected.get("paid_at") is None

        replacement = post_invoice(poa["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 100000},
        ], invoice_number="INV-A2")
        assert replacement["status"] == "PAYABLE", (
            "REJECTED invoice reopens the PO for a fresh invoice"
        )

        closed = api.create_invoice(
            pob["id"],
            {
                "invoice_number": "INV-B2",
                "lines": [{"line_no": 0, "quantity": 1, "unit_price_cents": 100000}],
            },
            AP_H,
        )
        validate_error(closed, ApiErrorId.ERR_PO_INVOICING_CLOSED, 409)
