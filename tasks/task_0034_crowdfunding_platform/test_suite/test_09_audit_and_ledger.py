"""Audit log access and the escrow ledger view.

PRD references:
  - §2.10 Cascades, Auditing, and the Escrow Ledger
  - §3.13 Audit Log Access and the Escrow Ledger View
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_user_headers,
    drive_clock_past_deadline,
    emit_payment,
    find_audit_entries,
    find_ledger_entries,
    list_audit_log,
    list_escrow_ledger,
    place_order,
    setup_live_project,
    setup_succeeded_with_authorized_order,
    validate_error,
    validate_paginated,
)


class TestAuditLogAccess:
    @pytest.mark.parametrize(
        "role",
        ["Initiator", "Backer", "ContentReviewer", "LegalReviewer",
         "FinancialReviewer"],
    )
    def test_audit_log_restricted_to_platform_admin(self, api, role):
        """PRD §3.13: 'The audit log is filterable by subject_type,
        subject_id, and event_type, paginated through limit and offset,
        and is restricted to PlatformAdmin callers.'

        Claim: non-PlatformAdmin → ERR_FORBIDDEN on GET /audit-log.
        """
        headers = build_user_headers(f"u-{role}", role)
        res = api.list_audit_log(headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_audit_log_records_charge_fund_flow(self, api):
        """PRD §2.10: 'whose event_type is one of STATUS_CHANGE, FUND_FLOW,
        REFUND_EXECUTED, SETTLEMENT_PAID, REVIEW_DECISION, or
        EXTERNAL_EVENT_RECEIVED.'
        PRD §3.6: 'an AuditLogEntry of type FUND_FLOW is appended.'

        Claim: after charge SUCCESS, a FUND_FLOW audit entry exists for
        the order.
        """
        ctx = setup_succeeded_with_authorized_order(
            funding_target_cents=5_000, reward_pledge_cents=10_000,
            deadline_hours_from_now=24.5,
        )
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        emit_payment(ctx["order"]["id"], "SUCCESS")
        entries = list_audit_log(
            subject_type="ORDER", subject_id=ctx["order"]["id"],
            event_type="FUND_FLOW",
        )
        fund_flows = find_audit_entries(
            entries, subject_type="ORDER", subject_id=ctx["order"]["id"],
            event_type="FUND_FLOW",
        )
        assert len(fund_flows) >= 1, (
            "PRD §3.6 requires a FUND_FLOW audit entry on order CHARGED."
        )


class TestEscrowLedgerAccess:
    def test_escrow_ledger_records_auth_hold_on_order(self, api):
        """PRD §3.4: 'An EscrowLedgerEntry of type AUTH_HOLD is inserted
        on the project's ledger.'

        Claim: after order create on a LIVE project, project's ledger
        contains an AUTH_HOLD entry for the order.
        """
        from test_helpers import create_backer
        _, project, reward = setup_live_project(
            category="TECH", reward_pledge_cents=5_000,
            reward_type="DIGITAL", funding_target_cents=10_000_000,
        )
        backer = create_backer()
        order = place_order(project=project, reward=reward, backer=backer)
        ledger = list_escrow_ledger(project["id"])
        auth_holds = find_ledger_entries(
            ledger, entry_type="AUTH_HOLD", order_id=order["id"]
        )
        assert len(auth_holds) >= 1

    def test_escrow_ledger_records_charge_capture_after_charged(self, api):
        """PRD §3.6: 'the EscrowLedgerEntry of type CHARGE_CAPTURE is
        finalized, additional COMMISSION_HOLD and CHANNEL_FEE entries
        are inserted'.

        Claim: after charge SUCCESS, the ledger has CHARGE_CAPTURE +
        COMMISSION_HOLD + CHANNEL_FEE for the order.
        """
        ctx = setup_succeeded_with_authorized_order(
            funding_target_cents=5_000, reward_pledge_cents=10_000,
            deadline_hours_from_now=24.5,
        )
        drive_clock_past_deadline(project=ctx["project"], past_seconds=1)
        emit_payment(ctx["order"]["id"], "SUCCESS")
        ledger = list_escrow_ledger(ctx["project"]["id"])
        order_id = ctx["order"]["id"]
        types_for_order = {
            e["entry_type"] for e in ledger if e.get("order_id") == order_id
        }
        assert "CHARGE_CAPTURE" in types_for_order
        assert "COMMISSION_HOLD" in types_for_order
        assert "CHANNEL_FEE" in types_for_order

    def test_escrow_ledger_restricted_to_initiator_or_admin(self, api):
        """PRD §3.13: 'The per-project escrow ledger is restricted to the
        owning initiator and platform admins'.

        Claim: a Backer hitting another project's escrow-ledger →
        ERR_FORBIDDEN.
        """
        _, project, _ = setup_live_project(
            category="TECH", reward_pledge_cents=5_000,
            reward_type="DIGITAL", funding_target_cents=10_000_000,
        )
        # Use a Backer header (entity-backed but not the owner of this
        # project; this is a forbidden-by-role check).
        from test_helpers import create_backer, make_backer_headers
        backer = create_backer()
        res = api.list_escrow_ledger(
            project["id"], make_backer_headers(backer["id"])
        )
        validate_error(res, "ERR_FORBIDDEN")
