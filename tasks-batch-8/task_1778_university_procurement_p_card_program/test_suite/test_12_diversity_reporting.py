"""Supplier-diversity reporting: committed vs paid bases, input-set filtering."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_requisition,
    create_department,
    create_vendor,
    get_success_data,
    issue_po_ok,
    post_invoice,
    post_receipt,
    requisition_line,
    validate_error,
)
from test_helpers.fixtures import ADMIN, AP_CLERK, BUYER

ADMIN_H = ADMIN
AP_H = AP_CLERK
BUYER_H = BUYER


def _report(api, dept_id, basis):
    return get_success_data(
        api.get_diversity_report(dept_id, ADMIN_H, params={"basis": basis})
    )


class TestCommittedVsPaidBasis:
    def _setup_two_pos(self, api):
        """PO-A 400,000 to a WBE vendor; PO-B 600,000 to a non-diverse vendor;
        both fully received and invoiced at exact price; only INV-B paid."""
        dept = create_department(name="Biology", diversity_goal_pct=0.25)
        v1 = create_vendor(
            legal_name="DiverseCo", diversity_certification="WBE",
            sustainability_tier="GOLD",
        )
        v2 = create_vendor(legal_name="PlainCo")
        ra = create_approved_requisition(
            department_id=dept["id"], vendor_id=v1["id"],
            lines=[requisition_line(
                commodity_code="OFF", description="chairs",
                unit_price_cents=400000, cost_category="SUPPLIES",
            )],
        )
        poa = issue_po_ok(ra["id"])
        post_receipt(poa["id"], [{"line_no": 0, "quantity": 1}])
        inva = post_invoice(poa["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 400000},
        ], invoice_number="INV-A")

        rb = create_approved_requisition(
            department_id=dept["id"], vendor_id=v2["id"],
            lines=[requisition_line(
                commodity_code="OFF", description="desks",
                unit_price_cents=600000, cost_category="SUPPLIES",
            )],
        )
        pob = issue_po_ok(rb["id"])
        post_receipt(pob["id"], [{"line_no": 0, "quantity": 1}])
        invb = post_invoice(pob["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 600000},
        ], invoice_number="INV-B")
        get_success_data(api.pay_invoice(invb["id"], AP_H))
        return dept, inva

    def test_diversity_bases_diverge_before_diverse_invoice_paid(self, api):
        """PRD §3.10: "the committed basis counts orders at issue regardless of
        payment, while the paid basis counts invoices only once paid, so identical
        underlying purchases yield different ratios until invoices settle."
        PRD §3.10: "a `ratio` equal to the diverse spend divided by the total
        spend rounded half up to exactly four decimal places — defined as 0.0000
        when the total spend is zero — and `goal_met`, true exactly when the
        ratio reaches the department's `diversity_goal_pct`."

        Design: Difficulty/dual_variant_calc/diversity_ratio_committed_vs_paid_basis
        """
        dept, _ = self._setup_two_pos(api)
        committed = _report(api, dept["id"], "COMMITTED")
        assert committed["diverse_spend_cents"] == 400000
        assert committed["total_spend_cents"] == 1000000
        assert committed["ratio"] == pytest.approx(0.4000, abs=1e-9)
        assert committed["goal_met"] is True

        paid = _report(api, dept["id"], "PAID")
        assert paid["diverse_spend_cents"] == 0
        assert paid["total_spend_cents"] == 600000
        assert paid["ratio"] == pytest.approx(0.0000, abs=1e-9)
        assert paid["goal_met"] is False

    def test_diversity_paid_basis_catches_up_after_payment(self, api):
        """PRD §3.10: "on the `PAID` basis it sums `total_cents` over paid
        invoices whose purchase order belongs to the department, with the same
        diverse-vendor restriction".

        Design: Difficulty/dual_variant_calc/diversity_ratio_committed_vs_paid_basis
        """
        dept, inva = self._setup_two_pos(api)
        get_success_data(api.pay_invoice(inva["id"], AP_H))
        paid = _report(api, dept["id"], "PAID")
        assert paid["diverse_spend_cents"] == 400000
        assert paid["total_spend_cents"] == 1000000
        assert paid["ratio"] == pytest.approx(0.4000, abs=1e-9)
        assert paid["goal_met"] is True


class TestReportInputSetFiltering:
    def test_diversity_report_filters_cancelled_and_rejected(self, api):
        """PRD §3.10: "the report sums `total_cents` over the department's
        purchase orders whose fulfillment is anything other than `CANCELLED`"
        (committed) and "on the `PAID` basis it sums `total_cents` over paid
        invoices whose purchase order belongs to the department, with the same
        diverse-vendor restriction" — a REJECTED invoice is never paid and never
        enters the paid basis.

        Design: Corner/calculations/diversity_report_excludes_cancelled_and_rejected
        """
        dept = create_department(name="Design", diversity_goal_pct=0.25)
        v1 = create_vendor(legal_name="DivCo", diversity_certification="MBE")
        v2 = create_vendor(legal_name="PlainInc")

        # PO-A (diverse, 400,000): issued, then cancelled before any receipt.
        ra = create_approved_requisition(
            department_id=dept["id"], vendor_id=v1["id"],
            lines=[requisition_line(
                commodity_code="DES", description="studio",
                unit_price_cents=400000, cost_category="SERVICES",
            )],
        )
        poa = issue_po_ok(ra["id"])
        get_success_data(api.cancel_purchase_order(poa["id"], BUYER_H))

        # PO-B (non-diverse, 600,000): received, invoiced at price, paid.
        rb = create_approved_requisition(
            department_id=dept["id"], vendor_id=v2["id"],
            lines=[requisition_line(
                commodity_code="DES", description="print",
                unit_price_cents=600000, cost_category="SERVICES",
            )],
        )
        pob = issue_po_ok(rb["id"])
        post_receipt(pob["id"], [{"line_no": 0, "quantity": 1}])
        invb = post_invoice(pob["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 600000},
        ], invoice_number="INV-B")
        get_success_data(api.pay_invoice(invb["id"], AP_H))

        # PO-C (diverse, 200,000): received, invoiced with a huge variance,
        # invoice REJECTED — but the PO itself is FULLY_RECEIVED, not CANCELLED.
        rc = create_approved_requisition(
            department_id=dept["id"], vendor_id=v1["id"],
            lines=[requisition_line(
                commodity_code="DES", description="photo",
                unit_price_cents=200000, cost_category="SERVICES",
            )],
        )
        poc = issue_po_ok(rc["id"])
        post_receipt(poc["id"], [{"line_no": 0, "quantity": 1}])
        invc = post_invoice(poc["id"], [
            {"line_no": 0, "quantity": 1, "unit_price_cents": 250000},
        ], invoice_number="INV-C")
        # variance 50,000 > tolerance round_half_up(0.02 * 200,000) = 4,000
        assert invc["status"] == "EXCEPTION"
        assert invc["exception_reason"] == "PRICE_VARIANCE"
        rejected = get_success_data(
            api.resolve_invoice_exception(
                invc["id"],
                {"action": "REJECT_INVOICE", "comment": "billing error"},
                AP_H,
            )
        )
        assert rejected["status"] == "REJECTED"

        committed = _report(api, dept["id"], "COMMITTED")
        # PO-A drops out entirely (CANCELLED). PO-C still counts — its
        # fulfillment is FULLY_RECEIVED, and the committed basis counts orders
        # at issue regardless of payment.
        assert committed["total_spend_cents"] == 800000
        assert committed["diverse_spend_cents"] == 200000
        assert committed["ratio"] == pytest.approx(0.2500, abs=1e-9)
        assert committed["goal_met"] is True

        paid = _report(api, dept["id"], "PAID")
        assert paid["total_spend_cents"] == 600000
        assert paid["diverse_spend_cents"] == 0
        assert paid["ratio"] == pytest.approx(0.0000, abs=1e-9)
        assert paid["goal_met"] is False
