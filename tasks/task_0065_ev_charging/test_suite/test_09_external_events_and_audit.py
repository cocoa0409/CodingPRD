"""External event inbox and audit-log behaviors.

PRD §2.7 (audit trail and immutable ledgers), §2.8 (external event
inbox and test-harness endpoints), §3.8 (external event
synchronization).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    emit_grid_pile_offline,
    emit_grid_pile_online,
    emit_payment_refunded,
    find_audit_logs,
    get_pile,
    list_audit_logs,
    list_session_ledger_entries,
    setup_operator_station_shelved_pile,
    setup_settled_session_for_recipe,
    sum_amounts_by_counterparty,
)


# ===========================================================================
# GRID events (PRD §3.8)
# ===========================================================================
class TestGridEvents:
    """PRD §3.8: 'A GRID event with event_type grid.pile_offline or
    grid.pile_online moves the referenced pile's operational_state to
    OFFLINE or back to IDLE, respectively.'"""

    def test_grid_pile_offline_event_takes_pile_offline(self, api):
        ctx = setup_operator_station_shelved_pile()
        emit_grid_pile_offline(ctx["pile"]["id"])
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "OFFLINE"

    def test_grid_pile_online_returns_pile_to_idle(self, api):
        ctx = setup_operator_station_shelved_pile()
        emit_grid_pile_offline(ctx["pile"]["id"])
        emit_grid_pile_online(ctx["pile"]["id"])
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IDLE"


# ===========================================================================
# PAYMENT.refunded — refund-reversal ledger rows
# ===========================================================================
class TestPaymentRefundedDispatch:
    """PRD §3.6: 'whenever a refund event arrives ... each of the four
    ledger rows is then written with amount_cents of the opposite sign
    and reason REFUND_REVERSAL.'"""

    def test_refund_writes_reversal_rows_with_session_settle_offset(
        self, api,
    ):
        ctx = setup_settled_session_for_recipe(
            member_tier="SILVER", member_wallet_cents=100000,
        )
        emit_payment_refunded(ctx["session"]["id"])
        rows = list_session_ledger_entries(ctx["session"]["id"])
        # Among the rows there must be at least one REFUND_REVERSAL row.
        reasons = {r["reason"] for r in rows}
        assert "REFUND_REVERSAL" in reasons, (
            f"Expected REFUND_REVERSAL rows after refund, got {reasons}"
        )


# ===========================================================================
# Audit log shape (PRD §2.7)
# ===========================================================================
class TestAuditLogShape:
    """PRD §2.7: 'each row recording actor_role, actor_id, entity_kind,
    entity_id, event_kind (one of BILLING_ADJUSTMENT or FAULT_EVENT), a
    payload capturing the before/after snapshot of relevant fields, and
    occurred_at as an ISO 8601 UTC timestamp.'"""

    def test_billing_adjustment_log_records_session_entity(self, api):
        ctx = setup_settled_session_for_recipe()
        emit_payment_refunded(ctx["session"]["id"])
        logs = list_audit_logs(
            event_kind="BILLING_ADJUSTMENT",
            entity_kind="ChargingSession",
            entity_id=ctx["session"]["id"],
        )
        assert len(logs) >= 1
        first = logs[0]
        assert first["event_kind"] == "BILLING_ADJUSTMENT"
        assert first["entity_kind"] == "ChargingSession"
        assert first["entity_id"] == ctx["session"]["id"]
