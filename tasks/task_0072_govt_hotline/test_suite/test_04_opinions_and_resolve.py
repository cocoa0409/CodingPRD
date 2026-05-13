"""Opinion submission, opinion aggregation, and resolve preconditions.

PRD §3.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    DISP, HO, PA,
    accept_assignment,
    classify,
    dispatch,
    find_lead_assignment,
    find_supporting_assignments,
    get_department,
    get_handler,
    get_work_order,
    list_sync_events,
    list_supervision_tasks,
    make_department_handler_headers,
    register_work_order,
    resolve,
    resolve_work_order_payload,
    setup_all_opinions_submitted,
    setup_in_progress,
    setup_routing_world,
    setup_supporting_accepted,
    submit_opinion,
    submit_opinion_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Opinion submission side effects (PRD §3.7)
# ===========================================================================
class TestOpinionSubmission:
    """PRD §3.7: 'The side-effects move stage_status to
    OPINION_SUBMITTED, stamp opinion_submitted_at to the current time,
    decrement the department's pending_work_count by 1, and decrement
    the handler's open_assignment_count by 1.'"""

    def test_opinion_submit_moves_stage_status(self, api):
        """PRD §3.7: 'The side-effects move stage_status to
        OPINION_SUBMITTED.'"""
        world = setup_supporting_accepted(num_supporting=1)
        sup_assign = world["supporting_assignments"][0]
        sup_handler = world["supporting_handlers"][0]
        data = submit_opinion(
            world["work_order"]["id"], sup_assign["id"], sup_handler,
            opinion_decision="AGREE",
        )
        assert data["stage_status"] == "OPINION_SUBMITTED"
        assert data["opinion_decision"] == "AGREE"

    def test_opinion_submit_decrements_pending_and_open(self, api):
        """PRD §3.7: 'decrement the department's pending_work_count by
        1, and decrement the handler's open_assignment_count by 1.'"""
        world = setup_supporting_accepted(num_supporting=1)
        sup_assign = world["supporting_assignments"][0]
        sup_handler = world["supporting_handlers"][0]
        sup_dept = world["supporting_departments"][0]
        before_dept = get_department(sup_dept["id"])
        before_hand = get_handler(sup_handler["id"])
        submit_opinion(
            world["work_order"]["id"], sup_assign["id"], sup_handler,
            opinion_decision="AGREE",
        )
        after_dept = get_department(sup_dept["id"])
        after_hand = get_handler(sup_handler["id"])
        assert after_dept["pending_work_count"] == (
            before_dept["pending_work_count"] - 1
        )
        assert after_hand["open_assignment_count"] == (
            before_hand["open_assignment_count"] - 1
        )

    def test_opinion_on_lead_assignment_rejected(self, api):
        """PRD §3.7: 'The transition is permitted only when the
        assignment's role is SUPPORTING and its stage_status is
        ACCEPTED.'"""
        world = setup_in_progress()
        lead = world["lead_assignment"]
        resp = api.submit_opinion(
            world["work_order"]["id"], lead["id"],
            submit_opinion_payload(opinion_decision="AGREE"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        # PRD §2.6 priority 9 lists ERR_ASSIGNMENT_NOT_PENDING for the
        # assignment-state check on /opinion.
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING.value)


# ===========================================================================
# Resolve preconditions and opinion aggregation (PRD §3.7)
# ===========================================================================
class TestResolveJointHandling:
    """PRD §3.7: 'when joint_handling is true every supporting
    assignment must be in OPINION_SUBMITTED (otherwise priority-16
    fires with ERR_OPINIONS_INCOMPLETE)... the current aggregated
    opinion decision must not be DISAGREE_BLOCKING (otherwise
    priority-17 fires with ERR_DISAGREEMENT_UNRESOLVED).'"""

    def test_resolve_without_supporting_opinions_yields_opinions_incomplete(
        self, api,
    ):
        """PRD §3.7: 'when joint_handling is true every supporting
        assignment must be in OPINION_SUBMITTED (otherwise priority-16
        fires with ERR_OPINIONS_INCOMPLETE).'"""
        world = setup_supporting_accepted(num_supporting=1)
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="trying"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPINIONS_INCOMPLETE.value)

    def test_resolve_when_majority_disagree_blocking(self, api):
        """PRD §3.7: 'if D is greater than or equal to the ceiling of N
        divided by 2 the aggregated decision is DISAGREE_BLOCKING...
        the current aggregated opinion decision must not be
        DISAGREE_BLOCKING (otherwise priority-17 fires with
        ERR_DISAGREEMENT_UNRESOLVED).'

        N=2 supporting, D=1 disagree: ceil(2/2)=1, D >= 1 → blocking.
        """
        world = setup_all_opinions_submitted(
            supporting_decisions=["AGREE", "DISAGREE"],
        )
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="resolution"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISAGREEMENT_UNRESOLVED.value)

    def test_resolve_when_all_agree_succeeds_and_emits_event(self, api):
        """PRD §3.7: 'On success, the work-order status becomes
        RESOLVED... emits a SyncEvent with event_type equal to RESOLVED
        to each of the three downstream platforms.'"""
        world = setup_all_opinions_submitted(
            supporting_decisions=["AGREE", "AGREE"],
        )
        data = resolve(world["work_order"]["id"],
                       handler=world["lead_handler"],
                       resolution_summary="done")
        assert data["status"] == "RESOLVED"
        events = list_sync_events(
            work_order_id=world["work_order"]["id"], event_type="RESOLVED",
        )
        platforms = {e["target_platform"] for e in events}
        assert platforms == {"IM", "GOVT_AFFAIRS", "INTER_DEPT"}

    def test_resolve_minority_disagree_outvoted_succeeds(self, api):
        """PRD §3.7: 'otherwise the aggregated decision is
        DISAGREE_OUTVOTED.' OUTVOTED is not blocking, so /resolve must
        succeed.

        N=3 supporting, D=1 disagree, A=2 agree: ceil(3/2)=2, D < 2 →
        OUTVOTED.
        """
        world = setup_all_opinions_submitted(
            supporting_decisions=["AGREE", "AGREE", "DISAGREE"],
        )
        data = resolve(world["work_order"]["id"],
                       handler=world["lead_handler"])
        assert data["status"] == "RESOLVED"

    def test_resolve_single_handler_case_no_opinions_required(self, api):
        """PRD §3.7: 'If the work order's joint_handling is false, the
        aggregated decision is trivially AGREE (there are no supporting
        departments to dissent).'"""
        world = setup_in_progress(num_supporting=0)
        data = resolve(world["work_order"]["id"],
                       handler=world["lead_handler"])
        assert data["status"] == "RESOLVED"

    def test_resolve_with_paused_work_order_rejected(self, api):
        """PRD §3.7: 'the work order must not currently be paused
        (pause_started_at must be null — a paused case must resume
        before it can resolve).'"""
        from test_helpers import pause
        world = setup_in_progress()
        pause(world["work_order"]["id"], handler=world["lead_handler"])
        resp = api.resolve_work_order(
            world["work_order"]["id"],
            resolve_work_order_payload(resolution_summary="x"),
            make_department_handler_headers(world["lead_handler"]["id"]),
        )
        # PRD §3.7 calls this a precondition fail; the priority table
        # treats it as a state check (priority 8) → ERR_INVALID_STATE.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Escalation (PRD §3.7)
# ===========================================================================
class TestEscalation:
    """PRD §3.7: 'a supporting handler facing deadlock... may escalate
    their assignment from ACCEPTED to ESCALATED. The side-effects move
    the stage_status to ESCALATED, and if the parent work order
    already has a SupervisionTask in status equal to OPEN, its
    escalation_level is incremented by 1; otherwise a fresh
    SupervisionTask is created with reason equal to MANUAL, status
    equal to ESCALATED, and escalation_level equal to 1. The system
    emits a SyncEvent with event_type equal to ESCALATED.'"""

    def test_escalate_creates_supervision_task_and_sync_event(self, api):
        """PRD §3.7: 'a fresh SupervisionTask is created with reason
        equal to MANUAL, status equal to ESCALATED, and escalation_level
        equal to 1. The system emits a SyncEvent with event_type equal
        to ESCALATED to each of IM, GOVT_AFFAIRS, and INTER_DEPT.'"""
        world = setup_supporting_accepted(num_supporting=1)
        sup_assign = world["supporting_assignments"][0]
        sup_handler = world["supporting_handlers"][0]
        resp = api.escalate_assignment(
            world["work_order"]["id"], sup_assign["id"],
            make_department_handler_headers(sup_handler["id"]),
        )
        data = validate_success(resp)
        assert data["stage_status"] == "ESCALATED"
        tasks = list_supervision_tasks(
            work_order_id=world["work_order"]["id"],
        )
        manual = [t for t in tasks if t["reason"] == "MANUAL"]
        assert len(manual) == 1
        assert manual[0]["status"] == "ESCALATED"
        assert manual[0]["escalation_level"] == 1
        events = list_sync_events(
            work_order_id=world["work_order"]["id"], event_type="ESCALATED",
        )
        platforms = {e["target_platform"] for e in events}
        assert platforms == {"IM", "GOVT_AFFAIRS", "INTER_DEPT"}
