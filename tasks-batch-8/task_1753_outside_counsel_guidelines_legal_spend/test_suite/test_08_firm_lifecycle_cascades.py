"""Panel firm suspension cascade: open appeals auto-deny, lines upheld (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_panel_firm,
    get_invoice,
    get_line_item,
    ops_headers,
    setup_rejected_invoice_with_claimed_appeal,
    validate_success,
)


class TestFirmSuspendTwoHopCascade:
    """Suspending a firm auto-denies its open appeals (hop 1), which flips each
    underlying line REJECTED -> UPHELD and recomputes the invoice (hop 2)."""

    def test_suspend_auto_denies_open_appeals(self, api, legal_ops_headers):
        """PRD §3.1: "Suspension carries a two-hop cascade. Every appeal in `SUBMITTED` or `UNDER_REVIEW` status that was filed on any line item of any invoice belonging to the firm auto-transitions to `DENIED`, with its `resolution_note` set to `AUTO_DENIED_FIRM_SUSPENDED`."
        PRD §3.1: "a `LegalOpsReviewer` may move a firm `ACTIVE → SUSPENDED`, which blocks new invoices and new rate cards"

        Design: Difficulty/transitive_cascade/firm_suspend_two_hop_cascade
        """
        ctx = setup_rejected_invoice_with_claimed_appeal()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        matter_id, invoice_id = ctx["matter"]["id"], ctx["invoice"]["id"]
        assert ctx["appeal"]["status"] in ("SUBMITTED", "UNDER_REVIEW")

        suspended = validate_success(api.suspend_panel_firm(dept_id, firm_id, legal_ops_headers))
        assert_panel_firm(suspended)
        assert suspended["status"] == "SUSPENDED", (
            f"the firm itself transitions ACTIVE -> SUSPENDED, got {suspended['status']}"
        )

        appeal_after = validate_success(
            api.get_appeal(dept_id, matter_id, invoice_id, ctx["line"]["id"], ctx["appeal"]["id"], ops_headers())
        )
        assert appeal_after["status"] == "DENIED", (
            f"hop 1 auto-denies the open appeal, got {appeal_after['status']}"
        )
        assert appeal_after["resolution_note"] == "AUTO_DENIED_FIRM_SUSPENDED", (
            f"auto-denial stamps the fixed resolution note, got {appeal_after['resolution_note']!r}"
        )

    def test_suspend_upholds_line_and_recomputes_invoice(self, api, legal_ops_headers):
        """PRD §3.1: "Each such auto-denied appeal then triggers the standard denial cascade described in §3.6: the underlying line item flips from `REJECTED` to `UPHELD`, and the parent invoice's `approved_total_cents` is recomputed."
        PRD §3.6: "Denying (`UNDER_REVIEW → DENIED`) flips the line `REJECTED → UPHELD` and recomputes the invoice totals with no change in amount."

        Design: Difficulty/transitive_cascade/firm_suspend_two_hop_cascade
        """
        ctx = setup_rejected_invoice_with_claimed_appeal()
        dept_id, firm_id = ctx["dept"]["id"], ctx["firm"]["id"]
        matter_id, invoice_id = ctx["matter"]["id"], ctx["invoice"]["id"]
        validate_success(api.suspend_panel_firm(dept_id, firm_id, legal_ops_headers))

        line_after = get_line_item(dept_id, matter_id, invoice_id, ctx["line"]["id"])
        assert line_after["review_status"] == "UPHELD", (
            f"hop 2 flips the line REJECTED -> UPHELD, got {line_after['review_status']}"
        )
        inv = get_invoice(dept_id, matter_id, invoice_id)
        assert inv["approved_total_cents"] == 0, (
            f"an upheld line still contributes zero, got {inv['approved_total_cents']}"
        )
