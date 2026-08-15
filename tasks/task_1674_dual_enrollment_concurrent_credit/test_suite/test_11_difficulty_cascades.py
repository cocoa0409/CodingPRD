"""Difficulty rule transitive_cascade: the offering-cancel cascade that drops
REGISTERED enrollments and voids their invoices, and the drop -> waitlist
promotion -> fresh invoice chain (PRD 3.4, 3.5, 3.6, 3.7)."""
from test_helpers import (
    cancel_offering,
    drop_enrollment,
    first_invoice_for_enrollment,
    get_enrollment,
    get_invoice,
    get_offering,
    list_invoices_for_enrollment,
    pay_invoice,
    setup_mixed_enrollment_scenario,
)


def _setup_cancel_cascade():
    """Capacity 2: e1 REGISTERED with the family share (30000) paid, e2 REGISTERED
    with an untouched invoice, e3 WAITLISTED with waitlist_seq 1."""
    ctx = setup_mixed_enrollment_scenario(capacity=2, num_students=3)
    invoice1 = first_invoice_for_enrollment(ctx["enrollments"][0]["id"])
    pay_invoice(invoice1["id"], "FAMILY", 30000)
    ctx["invoice1"] = invoice1
    ctx["invoice2"] = first_invoice_for_enrollment(ctx["enrollments"][1]["id"])
    return ctx


class TestOfferingCancelCascadeDepth3:
    def test_cancel_moves_each_enrollment_branch_conditionally(self, api):
        """PRD 3.4: "The cascade is conditional on each enrollment's status:
        `PENDING_VERIFICATION` enrollments become `CANCELLED`; `WAITLISTED`
        enrollments become `CANCELLED`; `REGISTERED` enrollments become `DROPPED`
        (an administrative drop, not a student-initiated one), and each such
        dropped enrollment's `Invoice` is voided with `refund_pct` set to 100 and
        the refund estimate fields computed per the estimate rules of §3.7, with
        `refund_status` set to `DUE` if the sum of its payments is greater than
        zero and `NONE` otherwise."
        PRD 3.4: "`DROPPED`, `COMPLETED`, `CANCELLED`, and `EXPIRED` enrollments are
        untouched."

        Design: Difficulty/transitive_cascade/offering_cancel_cascade_depth3
        """
        ctx = _setup_cancel_cascade()
        cancelled = cancel_offering(ctx["offering"]["id"])
        assert cancelled["status"] == "CANCELLED"

        e1 = get_enrollment(ctx["enrollments"][0]["id"])
        e2 = get_enrollment(ctx["enrollments"][1]["id"])
        e3 = get_enrollment(ctx["enrollments"][2]["id"])
        assert e1["status"] == "DROPPED", f"REGISTERED branch -> DROPPED, got {e1['status']}"
        assert e2["status"] == "DROPPED", f"REGISTERED branch -> DROPPED, got {e2['status']}"
        assert e3["status"] == "CANCELLED", (
            f"WAITLISTED branch -> CANCELLED (not dropped), got {e3['status']}"
        )
        offering = get_offering(ctx["offering"]["id"])
        assert offering["seats_taken"] == 0, "The cascade releases every seat"

    def test_cancel_voids_invoices_with_payment_dependent_refund_status(self, api):
        """PRD 3.4: "each such dropped enrollment's `Invoice` is voided with
        `refund_pct` set to 100 and the refund estimate fields computed per the
        estimate rules of §3.7, with `refund_status` set to `DUE` if the sum of its
        payments is greater than zero and `NONE` otherwise."
        PRD 3.5: "No invoice is created for a `WAITLISTED` enrollment."

        Design: Difficulty/transitive_cascade/offering_cancel_cascade_depth3
        """
        ctx = _setup_cancel_cascade()
        cancel_offering(ctx["offering"]["id"])

        invoice1 = get_invoice(ctx["invoice1"]["id"])
        assert invoice1["status"] == "VOIDED"
        assert invoice1["refund_pct"] == 100
        assert invoice1["refund_estimate_cents"] == 120000, (
            f"Estimate variant on billed shares: 120000 x 100%, got "
            f"{invoice1['refund_estimate_cents']}"
        )
        assert invoice1["refund_status"] == "DUE", (
            "30000 had been paid, so the refund is DUE"
        )

        invoice2 = get_invoice(ctx["invoice2"]["id"])
        assert invoice2["status"] == "VOIDED"
        assert invoice2["refund_pct"] == 100
        assert invoice2["refund_estimate_cents"] == 120000
        assert invoice2["refund_status"] == "NONE", (
            "Nothing was paid on the second invoice, so refund_status stays NONE"
        )

        waitlisted_invoices = list_invoices_for_enrollment(ctx["enrollments"][2]["id"])
        assert waitlisted_invoices == [], (
            "The WAITLISTED enrollment never had an invoice to void"
        )


class TestDropTriggersPromotionInvoiceChain:
    def test_drop_promotes_the_waitlist_head(self, api):
        """PRD 3.6: "A seat released by a drop or a withdraw fires a promotion only
        when the offering's `status` is `OPEN`; a seat released while the offering
        is `IN_SESSION` or later simply stays free."
        PRD 3.6: "When the condition holds and at least one `WAITLISTED` enrollment
        exists for the offering, the system promotes the one holding the minimum
        `waitlist_seq`."
        PRD 3.6: "Promotion moves that enrollment to `REGISTERED`, increments
        `seats_taken` by 1, increments the offering's `version` again (on top of
        the increment from the drop or withdraw that released the seat), and
        creates a new `Invoice` for the promoted enrollment per §3.7."

        Design: Difficulty/transitive_cascade/drop_triggers_promotion_invoice_chain
        """
        ctx = setup_mixed_enrollment_scenario(capacity=1, num_students=2)
        e1, e2 = ctx["enrollments"]
        assert e1["status"] == "REGISTERED"
        assert e2["status"] == "WAITLISTED" and e2["waitlist_seq"] == 1

        dropped = drop_enrollment(e1["id"])
        assert dropped["status"] == "DROPPED"

        promoted = get_enrollment(e2["id"])
        assert promoted["status"] == "REGISTERED", (
            f"The freed seat itself promoted the waitlist head, got "
            f"{promoted['status']}"
        )
        assert promoted["waitlist_seq"] == 1
        offering = get_offering(ctx["offering"]["id"])
        assert offering["seats_taken"] == 1, (
            "The freed seat was immediately re-taken by the promotion"
        )

    def test_promotion_creates_a_fresh_invoice_and_voids_the_dropped_one(self, api):
        """PRD 3.6: "Promotion moves that enrollment to `REGISTERED`, increments
        `seats_taken` by 1, increments the offering's `version` again (on top of
        the increment from the drop or withdraw that released the seat), and
        creates a new `Invoice` for the promoted enrollment per §3.7."
        PRD 3.5: "It also settles the enrollment's invoice per §3.7 with
        `refund_pct` set to 100."

        Design: Difficulty/transitive_cascade/drop_triggers_promotion_invoice_chain
        """
        ctx = setup_mixed_enrollment_scenario(capacity=1, num_students=2)
        e1, e2 = ctx["enrollments"]
        invoice1 = first_invoice_for_enrollment(e1["id"])

        drop_enrollment(e1["id"])

        promoted_invoices = list_invoices_for_enrollment(e2["id"])
        assert len(promoted_invoices) == 1, (
            "The promotion itself creates the promoted enrollment's invoice"
        )
        promoted_invoice = promoted_invoices[0]
        assert promoted_invoice["status"] == "ISSUED"
        assert promoted_invoice["tuition_total_cents"] == 120000
        assert promoted_invoice["state_amount_cents"] == 90000
        assert promoted_invoice["district_amount_cents"] == 0
        assert promoted_invoice["family_amount_cents"] == 30000

        dropped_invoice = get_invoice(invoice1["id"])
        assert dropped_invoice["status"] == "VOIDED"
        assert dropped_invoice["refund_pct"] == 100
