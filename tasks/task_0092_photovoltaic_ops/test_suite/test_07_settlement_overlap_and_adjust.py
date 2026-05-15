"""Settlement-period overlap, invoice issuance, and revenue-adjust
compensating action (PRD §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_metering_record,
    advance_clock_to,
    create_investor_share,
    create_settlement_period,
    create_station,
    issue_invoice_payload,
    revenue_adjust_payload,
    setup_confirmed_settlement,
    start_reconciliation_payload,
    validate_error,
    validate_success,
)


class TestSettlementPeriodOverlap:
    """PRD §3.6 closed-open overlap semantics."""

    def test_overlap_with_confirmed_period_rejected(
        self, api, finance_headers,
    ):
        """PRD §3.6: "during the eventual confirmation step the
        system additionally verifies that no other CONFIRMED period
        on the same station has a half-open [period_start,
        period_end) interval that overlaps this one."

        Claim: confirming a second period whose window overlaps an
        already-CONFIRMED one yields ERR_SETTLEMENT_PERIOD_OVERLAP.
        """
        # First period confirmed.
        result = setup_confirmed_settlement(
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            period_end_clock="2026-02-02T00:00:00.000Z",
            on_grid_kwh=100.0,
            grid_company_confirmed_kwh=100.0,
            investor_shares=[("Alpha", 10000)],
        )
        station = result["station"]
        # Second period overlapping the first.
        second = create_settlement_period(
            station["id"],
            period_start="2026-01-15T00:00:00.000Z",
            period_end="2026-02-15T00:00:00.000Z",
        )
        add_metering_record(
            station["id"], second["id"],
            window_start="2026-01-15T00:00:00.000Z",
            window_end="2026-02-15T00:00:00.000Z",
            on_grid_kwh=50.0, pricing_channel="FEED_IN",
        )
        advance_clock_to("2026-02-16T00:00:00.000Z")
        api.start_reconciliation(
            second["id"], start_reconciliation_payload(50.0),
            finance_headers,
        )
        resp = api.confirm_settlement(second["id"], finance_headers)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP.value)


class TestIssueInvoice:
    """PRD §3.6 invoice issuance."""

    def test_issue_invoice_attaches_invoice_no(
        self, api, finance_headers,
    ):
        """PRD §3.6: "Issuing an invoice attaches a unique invoice_no
        payload to the period..."

        Claim: issue-invoice on a CONFIRMED period attaches invoice_no
        and moves state to INVOICED.
        """
        result = setup_confirmed_settlement(
            investor_shares=[("OnlyInv", 10000)],
        )
        period = result["period"]
        resp = api.issue_invoice(
            period["id"], issue_invoice_payload(invoice_no="INV-2026-001"),
            finance_headers,
        )
        data = validate_success(resp)
        assert data["state"] == "INVOICED"
        assert data["invoice_no"] == "INV-2026-001"

    def test_duplicate_invoice_no_rejected(self, api, finance_headers):
        """PRD §3.6: "if that invoice number has been used for any
        other settlement period anywhere on the platform, the
        request is rejected with ERR_INVOICE_DUPLICATE."

        Claim: re-using invoice_no across two periods →
        ERR_INVOICE_DUPLICATE.
        """
        first = setup_confirmed_settlement(
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            period_end_clock="2026-02-02T00:00:00.000Z",
            investor_shares=[("OnlyInv", 10000)],
        )
        second = setup_confirmed_settlement(
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-04-01T00:00:00.000Z",
            period_end_clock="2026-04-02T00:00:00.000Z",
            investor_shares=[("OnlyInv", 10000)],
        )
        api.issue_invoice(
            first["period"]["id"],
            issue_invoice_payload(invoice_no="INV-DUPLICATE"),
            finance_headers,
        )
        resp = api.issue_invoice(
            second["period"]["id"],
            issue_invoice_payload(invoice_no="INV-DUPLICATE"),
            finance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_DUPLICATE.value)


class TestRevenueAdjust:
    """PRD §3.6 compensating action."""

    def test_revenue_adjust_returns_to_reconciling(
        self, api, finance_headers,
    ):
        """PRD §3.6: "On success, the period's existing
        RevenueDistribution rows are deleted (the first compensation
        hop) and final_revenue_cny is set back to null while
        provisional_revenue_cny is recomputed from the metering lines
        (the second hop..."

        Claim: revenue-adjust on a CONFIRMED period returns it to
        RECONCILING with final_revenue_cny null.
        """
        result = setup_confirmed_settlement(
            investor_shares=[("OnlyInv", 10000)],
        )
        period = result["period"]
        assert period["state"] == "CONFIRMED"
        resp = api.revenue_adjust(
            period["id"], revenue_adjust_payload(reason="audit"),
            finance_headers,
        )
        adjusted = validate_success(resp)
        assert adjusted["state"] == "RECONCILING"
        assert adjusted["final_revenue_cny"] is None

    def test_revenue_adjust_after_invoiced_rejected(
        self, api, finance_headers,
    ):
        """PRD §3.6: "a once-INVOICED period cannot be
        revenue-adjusted at all."

        Claim: revenue-adjust on an INVOICED period → ERR_INVALID_STATE.
        """
        result = setup_confirmed_settlement(
            investor_shares=[("OnlyInv", 10000)],
        )
        period = result["period"]
        api.issue_invoice(
            period["id"], issue_invoice_payload(),
            finance_headers,
        )
        resp = api.revenue_adjust(
            period["id"], revenue_adjust_payload(),
            finance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
