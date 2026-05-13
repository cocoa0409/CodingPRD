"""Dispatch fan-out, assignment accept/reject/reassign, and the
department pending_work_count side effects.

PRD §3.4, §3.5, §3.13.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PA, HO, DISP,
    accept_assignment,
    classify,
    create_department,
    dispatch,
    find_first,
    find_lead_assignment,
    find_supporting_assignments,
    get_department,
    get_handler,
    get_work_order,
    list_assignments,
    list_sync_events,
    list_supervision_tasks,
    make_department_handler_headers,
    reassign_assignment_payload,
    reject_assignment_payload,
    register_work_order,
    setup_in_progress,
    setup_routing_world,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Dispatch fan-out (PRD §3.4)
# ===========================================================================
class TestDispatchFanout:
    """PRD §3.4: 'The transition creates one DepartmentAssignment row
    with role equal to LEAD and department_id equal to
    lead_department_id, in stage_status equal to DISPATCHED, and one
    further DepartmentAssignment row with role equal to SUPPORTING for
    each supporting department, each in stage_status equal to
    DISPATCHED.'"""

    def test_dispatch_creates_lead_and_supporting_rows(self, api):
        """PRD §3.4: assignment rows created for lead + every supporting
        department."""
        world = setup_routing_world(num_supporting=2)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        assigns = list_assignments(wo["id"])
        leads = [a for a in assigns if a["role"] == "LEAD"]
        sups = [a for a in assigns if a["role"] == "SUPPORTING"]
        assert len(leads) == 1, "Exactly one LEAD assignment"
        assert len(sups) == 2, "One SUPPORTING per supporting department"
        for a in assigns:
            assert a["stage_status"] == "DISPATCHED"

    def test_dispatch_increments_pending_for_each_touched_department(self, api):
        """PRD §3.4: 'For every department touched (lead and every
        supporting) the department's pending_work_count is incremented
        by 1.'"""
        world = setup_routing_world(num_supporting=1)
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        before_lead = get_department(world["lead_department"]["id"])
        before_sup = get_department(world["supporting_departments"][0]["id"])
        dispatch(wo["id"])
        after_lead = get_department(world["lead_department"]["id"])
        after_sup = get_department(world["supporting_departments"][0]["id"])
        assert after_lead["pending_work_count"] == (
            before_lead["pending_work_count"] + 1
        )
        assert after_sup["pending_work_count"] == (
            before_sup["pending_work_count"] + 1
        )

    def test_dispatch_emits_sync_event_to_three_platforms(self, api):
        """PRD §3.4: 'Dispatch emits a SyncEvent with event_type equal
        to DISPATCHED to each of the three downstream platforms — IM,
        GOVT_AFFAIRS, and INTER_DEPT.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        events = list_sync_events(
            work_order_id=wo["id"], event_type="DISPATCHED",
        )
        platforms = {e["target_platform"] for e in events}
        assert platforms == {"IM", "GOVT_AFFAIRS", "INTER_DEPT"}, (
            f"PRD §3.4 names exactly these three platforms; got {platforms}"
        )

    def test_priority_flag_dispatch_creates_supervision_task(self, api):
        """PRD §3.4: 'If priority_flag is true at dispatch time...the
        system creates a SupervisionTask with reason equal to
        HIGH_PRIORITY_AUTO, status equal to OPEN, and escalation_level
        equal to 0.'"""
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
        assert len(auto) == 1
        assert auto[0]["status"] == "OPEN"
        assert auto[0]["escalation_level"] == 0

    def test_dispatch_when_lead_department_suspended_rejected(self, api):
        """PRD §3.4: 'Dispatch by a Dispatcher advances CLASSIFIED to
        DISPATCHED, provided lead_department_id is not null, the lead
        department's status is ACTIVE, and every supporting department
        referenced has status equal to ACTIVE.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        # Suspend the lead department.
        api.update_department(
            world["lead_department"]["id"],
            {"status": "SUSPENDED"}, PA,
        )
        resp = api.dispatch_work_order(wo["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Accept (PRD §3.5)
# ===========================================================================
class TestAcceptAssignment:
    """PRD §3.5: 'The successful accept side-effects set the
    assignment's stage_status to ACCEPTED, stamp handler_id to the
    acting handler, set accepted_at to the current time, and increment
    Handler.open_assignment_count by 1.'"""

    def test_lead_accept_flips_workorder_to_in_progress(self, api):
        """PRD §3.5: 'When the accepted assignment is the lead
        assignment and the parent work order's status is DISPATCHED or
        REOPENED, the work-order status is advanced to IN_PROGRESS.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        accept_assignment(wo["id"], lead["id"], world["lead_handler"])
        wo_after = get_work_order(wo["id"])
        assert wo_after["status"] == "IN_PROGRESS"

    def test_accept_by_wrong_department_handler_rejected(self, api):
        """PRD §3.5: 'the acting handler's department_id equals the
        assignment's department_id, and the handler's own status is
        ACTIVE.'

        Claim: a handler in a foreign department cannot accept.
        """
        world = setup_routing_world()
        # A handler in a foreign department (different from lead).
        foreign_dept = create_department()
        # No handler exists in foreign_dept yet — create one.
        from test_helpers import create_handler
        foreign_handler = create_handler(department_id=foreign_dept["id"])
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        resp = api.accept_assignment(
            wo["id"], lead["id"],
            make_department_handler_headers(foreign_handler["id"]),
        )
        # Either ERR_INVALID_STATE or ERR_ASSIGNMENT_NOT_PENDING or
        # ERR_FORBIDDEN — PRD only states the precondition, not the
        # exact error. PRD §2.6 priority 9 lists
        # ERR_ASSIGNMENT_NOT_PENDING as the assignment-state check; PRD
        # doesn't pin a specific error_id for the "wrong department"
        # case, so we accept the broad outcome.
        assert resp.status_code in (403, 409, 422), (
            f"Wrong-department accept must fail; got {resp.status_code}"
        )

    def test_accept_already_accepted_rejected(self, api):
        """PRD §3.5: 'The acceptance succeeds only when the
        assignment's current stage_status is DISPATCHED...' Priority 9
        in PRD §2.6 yields ERR_ASSIGNMENT_NOT_PENDING.
        """
        world = setup_in_progress()
        # Try to accept the same LEAD assignment twice.
        lead = world["lead_assignment"]
        resp = api.accept_assignment(
            world["work_order"]["id"], lead["id"],
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING.value)


# ===========================================================================
# Handler reject (PRD §3.5)
# ===========================================================================
class TestRejectAssignment:
    """PRD §3.5: 'A handler may also reject an assignment back to the
    dispatcher when the assignment is still DISPATCHED and a
    rejection_reason (between 1 and 500 characters) is provided.'"""

    def test_handler_reject_decrements_pending_work_count(self, api):
        """PRD §3.5: 'the department's pending_work_count is decremented
        by 1 — this is one of the decrement obligations the pending
        invariant tracks.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        before = get_department(world["lead_department"]["id"])
        lead = find_lead_assignment(wo["id"])
        resp = api.reject_assignment(
            wo["id"], lead["id"],
            reject_assignment_payload(rejection_reason="not my area"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_success(resp)
        after = get_department(world["lead_department"]["id"])
        assert after["pending_work_count"] == before["pending_work_count"] - 1

    def test_reject_missing_reason_validation(self, api):
        """PRD §3.5: 'a rejection_reason (between 1 and 500 characters)
        is provided.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        lead = find_lead_assignment(wo["id"])
        resp = api.reject_assignment(
            wo["id"], lead["id"], {},
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Dispatcher reassign (PRD §3.5)
# ===========================================================================
class TestReassign:
    """PRD §3.5: 'Reassignment is a Dispatcher action. It is permitted
    either when the original assignment is still DISPATCHED, or when
    the original assignment is the lead and is currently REJECTED.'"""

    def test_reassign_lead_updates_workorder_lead_department(self, api):
        """PRD §3.5: 'when the role is LEAD — update the work order's
        lead_department_id to the target.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        # Create a new viable lead department serving the same jurisdiction.
        new_lead = create_department(
            jurisdiction_codes=[world["jurisdiction_code"]],
        )
        lead = find_lead_assignment(wo["id"])
        resp = api.reassign_assignment(
            wo["id"], lead["id"],
            reassign_assignment_payload(target_department_id=new_lead["id"]),
            DISP,
        )
        validate_success(resp)
        wo_after = get_work_order(wo["id"])
        assert wo_after["lead_department_id"] == new_lead["id"]

    def test_reassign_lead_to_non_jurisdiction_dept_rejected(self, api):
        """PRD §3.5: 'When the role being reassigned is the lead, the
        target department must also serve the work order's
        jurisdiction_code — either its jurisdiction_codes contains the
        work order's jurisdiction, or its jurisdiction_codes list is
        empty (the citywide marker). Otherwise the reassignment is
        rejected with ERR_JURISDICTION_MISMATCH (422).'"""
        world = setup_routing_world(jurisdiction_code="J0001")
        wo = register_work_order(
            jurisdiction_code="J0001",
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        # New dept serves a different non-citywide jurisdiction.
        non_serving = create_department(jurisdiction_codes=["J9999"])
        lead = find_lead_assignment(wo["id"])
        resp = api.reassign_assignment(
            wo["id"], lead["id"],
            reassign_assignment_payload(
                target_department_id=non_serving["id"],
            ),
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_JURISDICTION_MISMATCH.value)

    def test_reassign_target_dept_must_be_active(self, api):
        """PRD §3.5: 'the target department must exist and have status
        equal to ACTIVE.'"""
        world = setup_routing_world()
        wo = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo["id"])
        dispatch(wo["id"])
        # Suspended dept that would otherwise serve the jurisdiction.
        suspended = create_department(
            jurisdiction_codes=[world["jurisdiction_code"]],
        )
        api.update_department(suspended["id"], {"status": "SUSPENDED"}, PA)
        lead = find_lead_assignment(wo["id"])
        resp = api.reassign_assignment(
            wo["id"], lead["id"],
            reassign_assignment_payload(target_department_id=suspended["id"]),
            DISP,
        )
        # PRD §3.5: 'the target department must exist and have status
        # equal to ACTIVE.' PRD does not pin a specific error_id; we
        # accept any 4xx that indicates the precondition was rejected.
        assert resp.status_code >= 400


# ===========================================================================
# Path validation (PRD §2.5)
# ===========================================================================
class TestPathValidation:
    """PRD §2.5: 'Path segments are validated left-to-right: a missing
    WorkOrder yields ERR_WORK_ORDER_NOT_FOUND (404) before any check
    on the trailing segments runs, and an assignment that exists but
    belongs to a different work order than the one in the path yields
    ERR_ASSIGNMENT_NOT_FOUND (404).'"""

    def test_assignment_belonging_to_different_work_order_404(self, api):
        """PRD §2.5: 'an assignment that exists but belongs to a
        different work order than the one in the path yields
        ERR_ASSIGNMENT_NOT_FOUND (404).'"""
        # Create two separate work orders.
        world = setup_routing_world()
        wo1 = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo1["id"])
        dispatch(wo1["id"])
        lead1 = find_lead_assignment(wo1["id"])
        # Second WO under same routing world.
        wo2 = register_work_order(
            jurisdiction_code=world["jurisdiction_code"],
            category_code=world["category_rule"]["category_code"],
            sub_category_code=world["category_rule"]["sub_category_code"],
        )
        classify(wo2["id"])
        dispatch(wo2["id"])
        # Try to address wo1's lead assignment under wo2's path.
        resp = api.accept_assignment(
            wo2["id"], lead1["id"],
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value)

    def test_missing_workorder_in_path_returns_workorder_not_found(self, api):
        """PRD §2.5: 'a missing WorkOrder yields
        ERR_WORK_ORDER_NOT_FOUND (404) before any check on the trailing
        segments runs.'"""
        resp = api.accept_assignment(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["department_handler_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND.value)
