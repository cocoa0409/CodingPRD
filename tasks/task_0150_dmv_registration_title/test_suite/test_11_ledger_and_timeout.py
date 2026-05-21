"""Fee ledger audit view + the seven-day unpaid-timeout compensating
sweep.

PRD §3.7 (ledger), §3.8 (timeout), §3.11 (audit view).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    UNPAID_TIMEOUT_DAYS,
    ApiErrorId,
    TEST_USERS,
    add_days,
    add_seconds,
    advance_clock_to,
    assert_fee_ledger_entry,
    assert_fee_ledger_has_kinds,
    assert_ledger_sum_zero,
    current_clock,
    get_transfer_application,
    list_fee_ledger,
    mark_paid,
    parse_iso,
    setup_application_at_tax_assessed,
    setup_application_completed_titled,
    validate_error,
    validate_paginated,
)


class TestFeeLedgerListing:

    def test_list_fee_ledger_after_assessment(self, api):
        """PRD §3.7: "appends exactly three FeeLedgerEntry rows."
        PRD §3.11: "Any TaxAssessor, PlatformAdmin, or the owning
        Applicant may list the per-application audit trail of
        FeeLedgerEntry rows associated with a given TransferApplication."
        """
        base = setup_application_at_tax_assessed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=20000.00,
            trade_in_value=5000.00,
        )
        entries = list_fee_ledger(base["application"]["id"])
        assert len(entries) == 3
        for entry in entries:
            assert_fee_ledger_entry(entry)
        assert_fee_ledger_has_kinds(
            entries, ["SALES_TAX", "REG_FEE", "PROCESSING_FEE"],
        )

    def test_ledger_entry_has_no_updated_at_or_version(self, api):
        """PRD §2.4: "FeeLedgerEntry rows carry only id and
        occurred_at; they are append-only, never edited, and have no
        updated_at and no version."
        """
        base = setup_application_at_tax_assessed()
        entries = list_fee_ledger(base["application"]["id"])
        for entry in entries:
            assert "updated_at" not in entry or entry.get("updated_at") is None
            assert "version" not in entry or entry.get("version") is None

    def test_list_fee_ledger_pagination_envelope(self, api):
        """PRD §3.11: "The listing supports limit and offset
        pagination."
        """
        base = setup_application_at_tax_assessed()
        resp = api.list_fee_ledger(
            base["application"]["id"],
            TEST_USERS["tax_assessor_headers"],
            params={"limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestUnpaidTimeoutSweep:

    def test_seven_day_timeout_reverts_to_emissions_passed(self, api):
        """PRD §3.8: "For every TransferApplication whose status is
        TAX_ASSESSED, whose paid_at is still null, and whose updated_at
        plus seven days is at or before the new clock instant, the
        system reverts the application from TAX_ASSESSED back to
        EMISSIONS_PASSED."
        """
        base = setup_application_at_tax_assessed()
        app = base["application"]
        # paid_at is null.
        updated_at = parse_iso(app["updated_at"])
        # Advance clock to updated_at + 7d + 1ms.
        target = add_seconds(add_days(updated_at, UNPAID_TIMEOUT_DAYS), 1)
        advance_clock_to(target)
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "EMISSIONS_PASSED"
        assert app_after["fee_subtotal"] is None
        assert app_after["processing_fee"] is None
        assert app_after["total_due"] is None

    def test_seven_day_timeout_posts_refund_rows(self, api):
        """PRD §3.8: "appends three refund FeeLedgerEntry rows whose
        kind values are REFUND_TAX, REFUND_REG, and REFUND_PROCESSING
        and whose amount_cents values are the negatives of the original
        three rows so they sum to zero net cents per application."
        """
        base = setup_application_at_tax_assessed(
            application_type="TITLE_TRANSFER",
            residency_state="CA",
            declared_sale_price=20000.00,
            trade_in_value=5000.00,
        )
        app = base["application"]
        updated_at = parse_iso(app["updated_at"])
        advance_clock_to(add_seconds(add_days(updated_at, UNPAID_TIMEOUT_DAYS), 1))
        entries = list_fee_ledger(app["id"])
        # Should be six rows: three debits + three refunds.
        assert len(entries) == 6, f"expected 6 ledger rows, got {len(entries)}: {entries}"
        kinds = sorted(e["kind"] for e in entries)
        assert kinds == sorted([
            "SALES_TAX", "REG_FEE", "PROCESSING_FEE",
            "REFUND_TAX", "REFUND_REG", "REFUND_PROCESSING",
        ])
        # PRD §2.6: "the sum of all amount_cents values across its
        # ledger is exactly zero once a refund cycle completes."
        assert_ledger_sum_zero(entries)

    def test_timeout_does_not_revert_paid_application(self, api):
        """PRD §3.8: "whose paid_at is still null."

        Claim: paid applications are NOT reverted by the timeout
        sweep.
        """
        base = setup_application_at_tax_assessed()
        app = base["application"]
        mark_paid(base["owner"]["id"], app["id"])
        updated_at = parse_iso(get_transfer_application(app["id"])["updated_at"])
        advance_clock_to(add_seconds(add_days(updated_at, UNPAID_TIMEOUT_DAYS + 1), 0))
        app_after = get_transfer_application(app["id"])
        assert app_after["status"] == "TAX_ASSESSED"
        assert app_after["fee_subtotal"] is not None
