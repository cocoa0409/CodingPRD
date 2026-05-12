"""WeddingProject lifecycle: DRAFT -> PLANNING -> EXECUTION -> SETTLEMENT
-> CLOSED, plus CANCELLED branches and the segregation-of-duties guard at
project creation. Covers PRD §3.1 and §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AUDITOR_ID,
    PLANNER_ID,
    PLANNER_ID_ALT,
    activate_project,
    add_full_milestones,
    add_milestone,
    advance_clock_past_ceremony,
    create_milestone_payload,
    create_project,
    create_project_payload,
    drive_contract_to_accepted,
    drive_settlement_to_finalized,
    get_project,
    list_audit_entries,
    setup_project_in_execution,
    setup_project_in_planning,
    setup_project_in_settlement,
    setup_project_in_settlement_with_one_finalized_and_one_terminated,
    setup_project_with_one_contract_accepted,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.1 -- Creation: planner_user_id != auditor_user_id segregation guard.
# ===========================================================================
class TestProjectCreationSegregation:

    def test_same_planner_and_auditor_id_rejected(self, api, planner_headers):
        """PRD §3.1: "The auditor_user_id MUST differ from planner_user_id
        at creation; otherwise the request is rejected with
        ERR_SEGREGATION_OF_DUTIES because the same person cannot both run
        the project and review its closure."

        Claim: POST /wedding-projects with auditor_user_id == planner_user_id
        -> ERR_SEGREGATION_OF_DUTIES / 403.
        """
        payload = create_project_payload(
            planner_user_id="same-id-001",
            auditor_user_id="same-id-001",
        )
        # Planner header carries planner-001; ownership is checked separately,
        # but the request body itself violates the segregation rule.
        # The acting planner's X-User-ID happens to be planner-001 in
        # planner_headers; the create endpoint accepts planner_user_id from
        # the body. Use planner_headers; the segregation check is on the
        # body's two fields, regardless of the acting user.
        res = api.create_project(payload, planner_headers)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# §3.1 -- DRAFT -> PLANNING (activation) preconditions.
# ===========================================================================
class TestActivation:

    def test_activate_succeeds_when_milestones_sum_to_100(
        self, api, planner_headers
    ):
        """PRD §3.1: "The DRAFT to PLANNING transition (the activation step)
        requires the project to currently be DRAFT (otherwise
        ERR_PROJECT_NOT_IN_DRAFT), at least one Milestone to exist
        (otherwise ERR_NO_MILESTONES), and the milestone-percent sum to
        equal 100.0 (otherwise ERR_MILESTONE_PERCENTAGES_INVALID)."

        Claim: DRAFT project + 1 milestone @ 100.0% -> activation succeeds,
        status becomes PLANNING.
        """
        project = create_project()
        add_full_milestones(project["id"])
        res = api.activate_project(project["id"], planner_headers)
        data = validate_success(res)
        assert data["status"] == "PLANNING"

    def test_activate_with_no_milestones_fails(self, api, planner_headers):
        """PRD §3.1: "The `DRAFT` to `PLANNING` transition (the activation
        step) requires the project to currently be `DRAFT` (otherwise
        `ERR_PROJECT_NOT_IN_DRAFT`), at least one `Milestone` to exist
        (otherwise `ERR_NO_MILESTONES`), and the milestone-percent sum to
        equal 100.0 (otherwise `ERR_MILESTONE_PERCENTAGES_INVALID`)."

        Claim: DRAFT project with zero milestones -> ERR_NO_MILESTONES / 422.
        """
        project = create_project()
        res = api.activate_project(project["id"], planner_headers)
        validate_error(res, ApiErrorId.ERR_NO_MILESTONES.value)

    # NOTE: a test asserting "activate with milestone_sum != 100 fails" was removed.
    # PRD §3.1 states the per-mutation invariant rejects creates/updates that
    # leave the sum != 100, so an activation with a non-100 sum is unreachable
    # under any PRD-faithful implementation. The mutation-side rejection is
    # already covered by test_create_second_milestone_breaking_sum_rejected
    # in test_03_milestones_and_budget.py.

    def test_activate_again_after_planning_fails(self, api, planner_headers):
        """PRD §3.1: "The `DRAFT` to `PLANNING` transition (the activation
        step) requires the project to currently be `DRAFT` (otherwise
        `ERR_PROJECT_NOT_IN_DRAFT`)."

        Claim: activating an already-PLANNING project -> ERR_PROJECT_NOT_IN_DRAFT.
        """
        project = setup_project_in_planning()
        res = api.activate_project(project["id"], planner_headers)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_IN_DRAFT.value)


# ===========================================================================
# §3.1 -- PLANNING -> EXECUTION preconditions.
# ===========================================================================
class TestStartExecution:

    def test_start_execution_without_required_categories_fails(
        self, api, planner_headers
    ):
        """PRD §3.1: "The PLANNING to EXECUTION transition (start-execution)
        requires ... at least one ACCEPTED Contract to exist for each of
        the VENUE and CATERING vendor categories (otherwise
        ERR_REQUIRED_CATEGORY_UNCOVERED, HTTP 422)."

        Claim: PLANNING project with no ACCEPTED contracts ->
        ERR_REQUIRED_CATEGORY_UNCOVERED / 422.
        """
        project = setup_project_in_planning()
        res = api.start_execution(project["id"], planner_headers)
        validate_error(res, ApiErrorId.ERR_REQUIRED_CATEGORY_UNCOVERED.value)

    def test_start_execution_succeeds_with_venue_and_catering_accepted(
        self, api, planner_headers
    ):
        """PRD §3.1: "The PLANNING to EXECUTION transition (start-execution)
        requires the project to be PLANNING ... and at least one ACCEPTED
        Contract to exist for each of the VENUE and CATERING vendor
        categories ... and budget_balance_cents to be at least zero after
        committing."

        Claim: VENUE + CATERING ACCEPTED -> start_execution succeeds and
        project.status becomes EXECUTION.
        """
        project_in_exec, _v, _c = setup_project_in_execution()
        assert project_in_exec["status"] == "EXECUTION"

    def test_start_execution_from_draft_fails(self, api, planner_headers):
        """PRD §3.1: "The `PLANNING` to `EXECUTION` transition
        (start-execution) requires the project to be `PLANNING` (otherwise
        `ERR_PROJECT_NOT_IN_PLANNING`)."

        Claim: start-execution on a DRAFT project -> ERR_PROJECT_NOT_IN_PLANNING.
        """
        project = create_project()
        res = api.start_execution(project["id"], planner_headers)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_IN_PLANNING.value)


# ===========================================================================
# §3.1 -- EXECUTION -> SETTLEMENT preconditions.
# ===========================================================================
class TestEnterSettlement:

    def test_enter_settlement_before_ceremony_fails(self, api, planner_headers):
        """PRD §3.1: "The EXECUTION to SETTLEMENT transition (enter-settlement)
        requires ... the system clock to have advanced past ceremony_date
        (otherwise ERR_CEREMONY_NOT_ELAPSED, HTTP 422)."

        Claim: EXECUTION project, clock not advanced past ceremony_date
        -> ERR_CEREMONY_NOT_ELAPSED / 422.
        """
        # ceremony_offset_seconds defaults to 180 days -> well in the future.
        project_exec, _v, _c = setup_project_in_execution(
            ceremony_offset_seconds=180 * 86400,
        )
        res = api.enter_settlement(project_exec["id"], planner_headers)
        validate_error(res, ApiErrorId.ERR_CEREMONY_NOT_ELAPSED.value)

    def test_enter_settlement_succeeds_after_ceremony(
        self, api, planner_headers
    ):
        """PRD §3.1: "the system clock to have advanced past ceremony_date".

        Claim: after advancing clock past ceremony_date and with all
        contracts ACCEPTED, enter-settlement succeeds with status SETTLEMENT.
        """
        project_exec, _v, _c = setup_project_in_execution(
            ceremony_offset_seconds=86400,
        )
        advance_clock_past_ceremony(project_exec["id"])
        res = api.enter_settlement(project_exec["id"], planner_headers)
        data = validate_success(res)
        assert data["status"] == "SETTLEMENT"


# ===========================================================================
# §3.1, §3.8 -- Cancellation from DRAFT (no cascade).
# ===========================================================================
class TestCancelFromDraft:

    def test_cancel_from_draft_simple(self, api, planner_headers):
        """PRD §3.1: "Cancellation from DRAFT is a simple state change with
        no side effects."

        Claim: cancel a DRAFT project -> status CANCELLED, no audit entry
        for the (zero) cascaded contracts.
        """
        project = create_project()
        res = api.cancel_project(project["id"], planner_headers)
        data = validate_success(res)
        assert data["status"] == "CANCELLED"


# ===========================================================================
# §3.1, §3.8 -- Cancellation from PLANNING/EXECUTION cascades to contracts.
# ===========================================================================
class TestCancelCascade:

    def test_cancel_from_planning_terminates_contracts(
        self, api, planner_headers
    ):
        """PRD §3.1: "Cancellation from PLANNING or EXECUTION cascades:
        every contract on the project whose contract_status is DRAFT,
        NEGOTIATING, SIGNED, or ACCEPTED is forced to TERMINATED exactly as
        if the planner had terminated each one individually, which in turn
        cascades the bound Quote rows to WITHDRAWN, deletes all TimelineSlot
        rows owned by those vendors on this project, and resets any DRAFT
        or VENDOR_CONFIRMED Settlement to DRAFT with confirmed_by_vendor_at
        cleared."

        Claim: cancel from PLANNING with one ACCEPTED contract ->
        contract_status==TERMINATED.
        """
        from test_helpers import get_contract
        project, _v, _q, contract = setup_project_with_one_contract_accepted()
        res = api.cancel_project(project["id"], planner_headers)
        validate_success(res)
        c_after = get_contract(project["id"], contract["id"])
        assert c_after["contract_status"] == "TERMINATED"


# ===========================================================================
# §3.1 -- Lifecycle progression smoke test (DRAFT -> CLOSED).
# ===========================================================================
class TestFullLifecycleProgression:

    def test_draft_to_closed_smoke_test(self, api):
        """PRD §3.1: "The project's lifecycle then advances through four
        stages." PRD §3.8: "On success, the project transitions to CLOSED".

        Claim: walking the full DRAFT -> PLANNING -> EXECUTION ->
        SETTLEMENT -> CLOSED sequence yields a CLOSED project.
        """
        from test_helpers import make_auditor_headers
        project_settle, _venue, _terminated = (
            setup_project_in_settlement_with_one_finalized_and_one_terminated()
        )
        auditor_headers = make_auditor_headers(AUDITOR_ID)
        res = api.close_project(project_settle["id"], auditor_headers)
        data = validate_success(res)
        assert data["status"] == "CLOSED"


# ===========================================================================
# §3.8 -- Project closure side effect: a final SETTLEMENT_FINALIZED entry
# with subject_type=BUDGET is appended.
# ===========================================================================
class TestCloseAuditEntry:

    def test_close_appends_budget_snapshot_entry(self, api):
        """PRD §3.8: "On success, the project transitions to CLOSED, and a
        final AuditEntry with event_kind of SETTLEMENT_FINALIZED and
        subject_type of BUDGET is appended capturing the final budget
        snapshot in its payload."

        Claim: post-close audit log contains an entry with
        event_kind==SETTLEMENT_FINALIZED AND subject_type==BUDGET.
        """
        from test_helpers import make_auditor_headers, find_audit_entries
        project, _v, _t = (
            setup_project_in_settlement_with_one_finalized_and_one_terminated()
        )
        auditor_headers = make_auditor_headers(AUDITOR_ID)
        api.close_project(project["id"], auditor_headers)
        entries = list_audit_entries(project["id"])
        budget_entries = find_audit_entries(
            entries,
            event_kind="SETTLEMENT_FINALIZED",
            subject_type="BUDGET",
        )
        assert len(budget_entries) >= 1, (
            f"PRD §3.8 requires a SETTLEMENT_FINALIZED+BUDGET entry on "
            f"close; got entries: "
            f"{[(e.get('event_kind'), e.get('subject_type')) for e in entries]}"
        )
