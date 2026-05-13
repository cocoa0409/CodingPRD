"""Supervision tasks, audit logs, sync events, and validation-priority
ordering tests.

PRD §2.6, §2.9, §3.11.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    DISP, HO, PA, SUP,
    classify,
    dispatch,
    find_lead_assignment,
    get_work_order,
    list_audit_logs,
    list_supervision_tasks,
    list_sync_events,
    make_department_handler_headers,
    register_work_order,
    setup_followed_up,
    setup_in_progress,
    setup_resolved,
    setup_routing_world,
    update_work_order_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Audit logs (PRD §2.9)
# ===========================================================================
class TestAuditLog:
    """PRD §2.9: 'Every state-changing action writes an AuditLog row
    whose action is one of a fixed catalogue.'"""

    def test_register_action_recorded(self, api):
        """PRD §3.2: 'An AuditLog row with action REGISTER is written.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        logs = list_audit_logs(work_order_id=wo["id"], action="REGISTER")
        assert any(l["action"] == "REGISTER" for l in logs)

    def test_dispatch_action_recorded(self, api):
        """PRD §3.4: 'An AuditLog row with action DISPATCH is written.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        logs = list_audit_logs(work_order_id=wo["id"], action="DISPATCH")
        assert any(l["action"] == "DISPATCH" for l in logs)

    def test_audit_log_records_actor_role_and_id(self, api):
        """PRD §2.9: 'Each audit row stamps the acting actor_role and
        actor_id (taken from the request headers).'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        logs = list_audit_logs(work_order_id=wo["id"], action="REGISTER")
        reg = [l for l in logs if l["action"] == "REGISTER"]
        assert reg, "REGISTER audit row missing"
        row = reg[0]
        assert row["actor_role"] == "HotlineOperator"
        assert isinstance(row["actor_id"], str) and row["actor_id"]


# ===========================================================================
# Sync events filtering (PRD §2.9, §4)
# ===========================================================================
class TestSyncEventsFiltering:
    """PRD §2.9: '/sync-events accepts work_order_id, event_type,
    target_platform, and delivery_status filters.'"""

    def test_filter_by_event_type(self, api):
        """PRD §2.9: 'a fixed set of state transitions emits a
        SyncEvent... namely the events DISPATCHED, RESOLVED, CLOSED,
        REOPENED, and ESCALATED.'"""
        world = setup_resolved(num_supporting=0)
        wo_id = world["work_order"]["id"]
        events = list_sync_events(
            work_order_id=wo_id, event_type="RESOLVED",
        )
        assert all(e["event_type"] == "RESOLVED" for e in events)
        assert any(e["work_order_id"] == wo_id for e in events)

    def test_filter_by_target_platform(self, api):
        """PRD §2.9: 'a target_platform... filter.'"""
        world = setup_resolved(num_supporting=0)
        events = list_sync_events(target_platform="IM")
        assert all(e["target_platform"] == "IM" for e in events)


# ===========================================================================
# Supervision lifecycle (PRD §3.11)
# ===========================================================================
class TestSupervisionLifecycle:
    """PRD §3.11: 'A Supervisor may acknowledge an open task — moving
    its status from OPEN to ACKNOWLEDGED.'"""

    def test_supervisor_can_ack_open_task(self, api):
        """PRD §3.11: 'A Supervisor may acknowledge an open task —
        moving its status from OPEN to ACKNOWLEDGED and stamping
        last_reminder_at.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        classify(wo["id"])
        dispatch(wo["id"])
        tasks = list_supervision_tasks(work_order_id=wo["id"])
        auto = [t for t in tasks if t["reason"] == "HIGH_PRIORITY_AUTO"]
        assert auto, "Expected HIGH_PRIORITY_AUTO task"
        task = auto[0]
        resp = api.ack_supervision(task["id"], SUP)
        data = validate_success(resp)
        assert data["status"] == "ACKNOWLEDGED"

    def test_supervisor_can_close_after_resolved(self, api):
        """PRD §3.11: 'A Supervisor may close any supervision task...
        once the parent work order's status is one of RESOLVED,
        FOLLOWED_UP, or CLOSED.'"""
        # Build a resolved WO with urgency=CRITICAL so a supervision
        # task already exists.
        from test_helpers import (setup_in_progress, accept_assignment,
                                  resolve)
        # Build directly.
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            urgency="CRITICAL",
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        resolve(wo["id"], handler=world["lead_handler"])
        tasks = list_supervision_tasks(work_order_id=wo["id"])
        auto = [t for t in tasks if t["reason"] == "HIGH_PRIORITY_AUTO"]
        assert auto
        resp = api.close_supervision(auto[0]["id"], SUP)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"


# ===========================================================================
# Validation priority — state vs anonymous PII (PRD §2.6, priorities 8, 12)
# ===========================================================================
class TestValidationPriority:
    """PRD §2.6: 'When more than one validation could fire on the same
    request, they are evaluated in a fixed priority order so that the
    returned error_id is deterministic.'"""

    def test_patch_classified_with_pii_violation_state_wins(self, api):
        """PRD §2.6: 'the work-order state-permission check is priority
        8 (and surfaces as ERR_INVALID_STATE)... Business-safety checks
        for anonymous PII (priority 12, ERR_ANONYMOUS_PII_LEAK).'

        State check fires first, so an anonymous WO classified into
        CLASSIFIED that is then PATCHed with caller_phone returns
        ERR_INVALID_STATE, not ERR_ANONYMOUS_PII_LEAK.

        difficulty: priority_pair_validation_conflict/state_vs_business_safety_anonymous_pii_on_pause
        """
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
            anonymous=True,
        )
        classify(wo["id"])
        # PATCH applies only to REGISTERED; this WO is CLASSIFIED so
        # state precedes business_safety.
        resp = api.update_work_order(
            wo["id"],
            update_work_order_payload(caller_phone="+10000000000"),
            HO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
