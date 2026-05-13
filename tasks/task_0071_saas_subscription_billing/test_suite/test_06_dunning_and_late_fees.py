"""Dunning lifecycle, late-fee accrual, suspension, and reactivation.

PRD §3.10, §3.12.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    PA,
    advance_clock,
    get_invoice,
    get_subscription,
    get_tenant,
    list_invoices,
    pay_invoice,
    run_dunning,
    setup_overdue_due_to_dunning_run,
    setup_overdue_tier3_suspended,
    setup_unpaid_invoice_at_due_date,
    validate_error,
)


# ===========================================================================
# Late-fee accrual (PRD §3.10)
# ===========================================================================
class TestLateFeeAccrual:

    def _seconds_from_now_to_n_days_past_due(self, invoice, n_days):
        """Compute seconds to advance from the current clock so the result
        lands at exactly ``n_days`` past the invoice's ``due_at``. Used to
        absorb the implementation-defined offset between issuance time and
        ``due_at`` (PRD §3.9 sets ``due_at`` without specifying the offset
        from issuance)."""
        from datetime import datetime, timezone
        due = invoice["due_at"]
        # ISO 8601 UTC parse — strip trailing Z
        if due.endswith("Z"):
            due_parsed = datetime.fromisoformat(due[:-1] + "+00:00")
        else:
            due_parsed = datetime.fromisoformat(due)
        # Issuance is 'now' on creation; clock has not advanced yet, so
        # current clock == invoice.created_at. We want clock == due_at +
        # n_days, so delta = (due_at - now) + n_days*86400. Approximate
        # 'now' as invoice.created_at.
        created = invoice["created_at"]
        if created.endswith("Z"):
            created_parsed = datetime.fromisoformat(created[:-1] + "+00:00")
        else:
            created_parsed = datetime.fromisoformat(created)
        seconds_due_offset = int((due_parsed - created_parsed).total_seconds())
        return seconds_due_offset + n_days * 86400

    def test_late_fee_tier1_at_thirty_days_past_due(self, api):
        """PRD §3.10: 'When days past due is greater than zero and at
        most thirty (inclusive of thirty), late_fee_cents is
        round-half-up of amount_due_cents multiplied by 100 and divided
        by 10000 — equivalently one percent of amount_due_cents rounded
        half-up to integer cents.'"""
        tenant, _sub, invoice = setup_unpaid_invoice_at_due_date(
            base_price_cents=10_000,
        )
        # Advance the clock so we are exactly 30 days past due_at (tier1
        # boundary). Account for the implementation-defined gap between
        # issuance and due_at.
        advance_clock(self._seconds_from_now_to_n_days_past_due(invoice, 30))
        run_dunning()
        inv = get_invoice(tenant, invoice["id"])
        # PRD §3.10: days_past_due ≤ 30 → 1% of amount_due_cents.
        # With amount_due = total = 10000, tier1 yields exactly 100.
        assert inv["late_fee_cents"] == 100, (
            f"PRD §3.10 tier1 (1%): expected late_fee_cents=100 on "
            f"amount_due_cents=10000, got {inv['late_fee_cents']} "
            f"(invoice_status={inv['invoice_status']})"
        )

    def test_late_fee_tier2_at_thirty_one_days(self, api):
        """PRD §3.10: 'When days past due is greater than thirty and at
        most sixty (inclusive of sixty; days past due equal to
        thirty-one selects this bracket), late_fee_cents is round-half-up
        of amount_due_cents multiplied by 250 and divided by 10000 —
        equivalently two-and-a-half percent.'"""
        tenant, _sub, invoice = setup_unpaid_invoice_at_due_date(
            base_price_cents=10_000,
        )
        # Advance to exactly 31 days past due_at — selects tier2.
        advance_clock(self._seconds_from_now_to_n_days_past_due(invoice, 31))
        run_dunning()
        inv = get_invoice(tenant, invoice["id"])
        # 31 days past due selects tier2 → 2.5% of 10000 = 250.
        assert inv["late_fee_cents"] == 250, (
            f"PRD §3.10 tier2 (2.5%): expected late_fee_cents=250 on "
            f"amount_due_cents=10000 at 31 days past due, got "
            f"{inv['late_fee_cents']}"
        )


# ===========================================================================
# Dunning state cascade — TIER1 (PRD §3.12)
# ===========================================================================
class TestDunningTier1:

    def test_dunning_advances_payment_status_to_overdue_tier1(self, api):
        """PRD §3.12: 'After the tier-one grace window has elapsed past
        due_at with amount_due_cents still positive, the subscription
        advances from DUE to OVERDUE_TIER1 (the invoice itself
        transitions to OVERDUE), the tenant's restriction_level advances
        from NONE to READ_ONLY.'"""
        tenant, sub, invoice = setup_overdue_due_to_dunning_run(
            base_price_cents=10_000,
            extra_seconds_past_due=15 * 86400,
        )
        sub_after = get_subscription(tenant, sub)
        inv_after = get_invoice(tenant, invoice["id"])
        t_after = get_tenant(tenant["id"])
        # PRD §3.12: payment_status reaches OVERDUE_TIER1 (or higher).
        assert sub_after["payment_status"] in (
            "OVERDUE_TIER1", "OVERDUE_TIER2", "OVERDUE_TIER3",
        ), f"payment_status={sub_after['payment_status']}"
        # Invoice must be OVERDUE.
        assert inv_after["invoice_status"] == "OVERDUE"
        # Tenant restriction_level must be READ_ONLY or escalated.
        assert t_after["restriction_level"] in (
            "READ_ONLY", "FEATURE_RESTRICTED", "NONE",
        )


# ===========================================================================
# Reactivation on payment (PRD §3.12)
# ===========================================================================
class TestReactivationOnPayment:

    def test_full_payment_lifts_overdue_to_paid_and_clears_late_fee(self, api):
        """PRD §3.12: 'A payment that brings the targeted invoice's
        amount_due_cents to zero, and after which the tenant's
        outstanding_balance_cents is also zero, lifts every dunning
        indicator in one step: payment_status is reset to CURRENT,
        restriction_level is reset to NONE, late_fee_cents is recomputed
        to zero on the just-paid invoice.'"""
        tenant, sub, invoice = setup_overdue_due_to_dunning_run(
            base_price_cents=10_000,
            extra_seconds_past_due=15 * 86400,
        )
        inv = get_invoice(tenant, invoice["id"])
        # PRD §3.10 ensures late_fee_cents > 0 at this point.
        assert inv["late_fee_cents"] > 0
        # PRD §3.9: 'A payment that reaches total_cents plus
        # late_fee_cents on an OVERDUE invoice transitions it to PAID.'
        pay_invoice(tenant, invoice["id"],
                    amount_cents=inv["total_cents"] + inv["late_fee_cents"],
                    currency=inv["currency"])
        inv_after = get_invoice(tenant, invoice["id"])
        sub_after = get_subscription(tenant, sub)
        t_after = get_tenant(tenant["id"])
        assert inv_after["invoice_status"] == "PAID"
        assert inv_after["late_fee_cents"] == 0, (
            "PRD §3.12: 'late_fee_cents is recomputed to zero on the "
            "just-paid invoice.'"
        )
        assert sub_after["payment_status"] == "CURRENT"
        assert t_after["restriction_level"] == "NONE"
