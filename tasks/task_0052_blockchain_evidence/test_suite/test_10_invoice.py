"""Invoice issuance: SINGLE_EVIDENCE, SINGLE_BATCH, BILLING_PERIOD.

PRD §3.9, §2.10 priority 16, ERR_INVOICE_SCOPE_INVALID.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    assert_invoice,
    bring_batch_to_confirmed,
    bring_evidence_to_confirmed,
    create_customer_with_balance,
    create_evidence,
    create_invoice_payload,
    iso_z,
    make_customer_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# SINGLE_EVIDENCE scope (PRD §3.9)
# ===========================================================================
class TestInvoiceSingleEvidence:
    """PRD §3.9: 'When scope is SINGLE_EVIDENCE, the body carries
    scope_ref_id set to the id of a CONFIRMED Evidence;
    Invoice.total_cents is pinned to that evidence's
    per_evidence_fee_cents.'"""

    def test_single_evidence_total_matches_per_evidence_fee(self, api):
        """PRD §3.9: 'Invoice.total_cents is pinned to that evidence's
        per_evidence_fee_cents.'"""
        customer, ev = bring_evidence_to_confirmed(
            balance_cents=5_000,
            evidence_overrides={
                "evidence_type": "IMAGE", "storage_period_days": 30,
            },
        )
        # IMAGE / 30: 300 * 1.00 = 300.
        assert ev["per_evidence_fee_cents"] == 300
        res = api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="SINGLE_EVIDENCE",
                scope_ref_id=ev["id"],
            ),
            make_customer_headers(customer["id"]),
        )
        inv = validate_success(res, 201)
        assert_invoice(inv)
        assert inv["scope"] == "SINGLE_EVIDENCE"
        assert inv["total_cents"] == 300
        assert inv["status"] == "ISSUED"

    def test_invoice_against_non_confirmed_evidence_rejected(self, api):
        """PRD §3.9: 'An invoice whose scope is SINGLE_EVIDENCE against
        a non-CONFIRMED evidence — whose per_evidence_fee_cents would
        be null — is rejected with ERR_INVOICE_SCOPE_INVALID.'"""
        customer = create_customer_with_balance(balance_cents=0)
        evidence = create_evidence(customer)  # PENDING, no fee
        res = api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="SINGLE_EVIDENCE",
                scope_ref_id=evidence["id"],
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVOICE_SCOPE_INVALID.value)


# ===========================================================================
# SINGLE_BATCH scope (PRD §3.9)
# ===========================================================================
class TestInvoiceSingleBatch:
    """PRD §3.9: 'When scope is SINGLE_BATCH, the body carries
    scope_ref_id set to the id of a CONFIRMED Batch; Invoice.total_cents
    is pinned to that batch's total_fee_cents.'"""

    def test_single_batch_total_matches_batch_fee(self, api):
        customer, batch, _ = bring_batch_to_confirmed(
            member_count=2,
            evidence_overrides={
                "evidence_type": "DOCUMENT", "storage_period_days": 30,
            },
            balance_cents=10_000,
        )
        # 2 × DOCUMENT/30: per-line 200, subtotal 400, *0.95 = 380.
        assert batch["total_fee_cents"] == 380
        res = api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="SINGLE_BATCH",
                scope_ref_id=batch["id"],
            ),
            make_customer_headers(customer["id"]),
        )
        inv = validate_success(res, 201)
        assert inv["total_cents"] == 380


# ===========================================================================
# BILLING_PERIOD scope (PRD §3.9)
# ===========================================================================
class TestInvoiceBillingPeriod:
    """PRD §3.9: 'When scope is BILLING_PERIOD, the body omits
    scope_ref_id, supplies inclusive period_start and period_end
    timestamps, and the invoice's total_cents is the sum of every fee
    debited for this customer_id whose timestamp falls inside the
    closed interval [period_start, period_end]'.

    PRD §2.10 priority 16: 'On POST /invoices with scope of
    BILLING_PERIOD, period_start is at or before period_end and
    period_end is at or before the server's current time
    (ERR_PERIOD_INVALID).'"""

    def test_period_end_after_now_rejected(self, api, admin_headers):
        """PRD §2.10 priority 16: period_end > now rejects with
        ERR_PERIOD_INVALID."""
        customer = create_customer_with_balance(balance_cents=0)
        # Set the clock to a known past instant.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from test_helpers import clock_payload
        validate_success(api.advance_clock(
            clock_payload(iso_z(now)), admin_headers,
        ), 200)
        future = now + timedelta(days=30)
        res = api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="BILLING_PERIOD",
                period_start=iso_z(now - timedelta(days=10)),
                period_end=iso_z(future),
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_INVALID.value)

    def test_period_start_after_period_end_rejected(self, api,
                                                     admin_headers):
        """PRD §2.10 priority 16: 'period_start is at or before
        period_end' — violation → ERR_PERIOD_INVALID."""
        customer = create_customer_with_balance(balance_cents=0)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        from test_helpers import clock_payload
        validate_success(api.advance_clock(
            clock_payload(iso_z(now)), admin_headers,
        ), 200)
        res = api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="BILLING_PERIOD",
                period_start=iso_z(now - timedelta(days=1)),
                period_end=iso_z(now - timedelta(days=5)),
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PERIOD_INVALID.value)


# ===========================================================================
# Created in ISSUED, audit appended (PRD §3.9)
# ===========================================================================
class TestInvoiceLifecycle:
    """PRD §3.9: 'All Invoice rows are created in the ISSUED state and
    may be VOIDED administratively. Issuance also appends an audit row
    of event_type INVOICE_ISSUED.'"""

    def test_invoice_audit_row_appended(self, api):
        from test_helpers import list_audit_logs
        customer, ev = bring_evidence_to_confirmed()
        inv = validate_success(api.create_invoice(
            create_invoice_payload(
                customer_id=customer["id"],
                scope="SINGLE_EVIDENCE",
                scope_ref_id=ev["id"],
            ),
            make_customer_headers(customer["id"]),
        ), 201)
        rows = list_audit_logs(
            event_type="INVOICE_ISSUED",
            target_entity="Invoice",
            target_id=inv["id"],
        )
        assert len(rows) >= 1
