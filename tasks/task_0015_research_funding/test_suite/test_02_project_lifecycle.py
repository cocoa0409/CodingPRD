"""Project lifecycle tests: DRAFT → UNDER_REVIEW → APPROVED → ACTIVE → CLOSING → CLOSED.

PRD §3.1 (initiation, peer review, approval), §3.5 (closing audit cascade).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_by_days,
    advance_clock_to,
    add_three_approving_reviews,
    add_two_pending_reviews,
    append_peer_review,
    api_client,
    assert_project,
    create_draft_project,
    create_project_payload,
    create_and_activate_project,
    create_and_approve_project,
    future_dates,
    get_project,
    make_principal_investigator_headers,
    setup_active_project_with_budget,
    submit_project,
    validate_error,
    validate_success,
)
from datetime import datetime, timedelta, timezone


class TestProjectCreate:
    """PRD §3.1 project creation."""

    def test_create_draft_project(self, api):
        """PRD §3.1: "The new project lands in DRAFT status with no project_code yet
        — the code is null until approval."

        Claim: POST /projects returns 201 with status=DRAFT and project_code=null.
        """
        start, end = future_dates(api)
        payload = create_project_payload(
            principal_investigator_id="pi-create-test",
            planned_start_date=start, planned_end_date=end,
        )
        headers = make_principal_investigator_headers("pi-create-test")
        resp = api.create_project(payload, headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data.get("project_code") is None
        assert_project(data)


class TestProjectSubmit:
    """PRD §3.1 submission preconditions."""

    def test_submit_too_short_proposal(self, api):
        """PRD §3.1: "proposal_text must be at least 200 characters long
        (otherwise ERR_PROPOSAL_TOO_SHORT)."

        Claim: submit with proposal_text < 200 chars returns ERR_PROPOSAL_TOO_SHORT.
        """
        project = create_draft_project(api, pi_id="pi-short-prop", proposal_text="short text")
        headers = make_principal_investigator_headers("pi-short-prop")
        resp = api.submit_project(project["id"], headers)
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_TOO_SHORT.value)

    def test_submit_invalid_date_range(self, api):
        """PRD §3.1: "planned_end_date must be strictly greater than planned_start_date
        (otherwise ERR_INVALID_DATE_RANGE)."

        Claim: planned_end_date <= planned_start_date returns ERR_INVALID_DATE_RANGE at submit.
        """
        start, _ = future_dates(api)
        # Make end <= start to violate the rule (set end == start, which is NOT strictly greater).
        project = create_draft_project(api, pi_id="pi-bad-dates",
                                        planned_start_date=start,
                                        planned_end_date=start)
        headers = make_principal_investigator_headers("pi-bad-dates")
        resp = api.submit_project(project["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)

    def test_submit_start_in_past(self, api):
        """PRD §3.1: "planned_start_date must be at or after the current server time
        (otherwise ERR_START_IN_PAST)."

        Claim: planned_start_date in the past returns ERR_START_IN_PAST at submit.
        """
        # Build a project with a past start date by advancing the clock past it.
        project = create_draft_project(api, pi_id="pi-past-start",
                                         start_offset_days=1, duration_days=365)
        # Advance the clock to well past planned_start_date so submit sees start in past.
        advance_clock_by_days(api, days=10)
        headers = make_principal_investigator_headers("pi-past-start")
        resp = api.submit_project(project["id"], headers)
        validate_error(resp, ApiErrorId.ERR_START_IN_PAST.value)

    def test_submit_not_owner(self, api):
        """PRD §3.1: "Submission is restricted to the project's principal investigator:
        X-User-ID must equal principal_investigator_id, otherwise the request is rejected
        with ERR_NOT_PROJECT_OWNER."

        Claim: a PI with a different X-User-ID is rejected with ERR_NOT_PROJECT_OWNER.
        """
        project = create_draft_project(api, pi_id="pi-real-owner")
        wrong_headers = make_principal_investigator_headers("pi-imposter")
        resp = api.submit_project(project["id"], wrong_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER.value)

    def test_submit_advances_status(self, api):
        """PRD §3.1: "Submitting the project for review advances status from DRAFT to UNDER_REVIEW."

        Claim: a valid submit transitions DRAFT → UNDER_REVIEW.
        """
        project = create_draft_project(api, pi_id="pi-submit-ok")
        headers = make_principal_investigator_headers("pi-submit-ok")
        resp = api.submit_project(project["id"], headers)
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"


class TestProjectApproveAndReject:
    """PRD §3.1 approval and rejection."""

    def test_approve_requires_three_peer_reviews(self, api):
        """PRD §3.1: "The decision requires that at least three peer reviews exist for the
        project (otherwise ERR_INSUFFICIENT_REVIEWS), and that the count of reviews with
        recommendation set to APPROVE is strictly greater than the count of reviews with
        recommendation set to REJECT (otherwise ERR_REVIEW_CONSENSUS_NOT_MET)."

        # difficulty: boundary_precision_check/project_approve_empty_peer_review_set_boundary

        Claim: with only 2 peer reviews, approve returns ERR_INSUFFICIENT_REVIEWS.
        """
        from test_helpers import setup_project_in_under_review, TEST_USERS
        project, _ = setup_project_in_under_review(api, pi_id="pi-app-2reviews",
                                                     n_reviews=0)
        # exactly two peer reviews (boundary at count=2 < 3)
        add_two_pending_reviews(api, project["id"])
        admin = TEST_USERS["research_admin_headers"]
        resp = api.approve_project(project["id"], admin)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REVIEWS.value)

    def test_approve_succeeds_at_three_peer_reviews(self, api):
        """PRD §3.1: "The decision requires that at least three peer reviews exist for the
        project (otherwise ERR_INSUFFICIENT_REVIEWS), and that the count of reviews with
        recommendation set to APPROVE is strictly greater than the count of reviews with
        recommendation set to REJECT (otherwise ERR_REVIEW_CONSENSUS_NOT_MET)."

        # difficulty: boundary_precision_check/project_approve_empty_peer_review_set_boundary

        Claim: with the third APPROVE peer review attached, approve succeeds and status=APPROVED.
        """
        from test_helpers import setup_project_in_under_review, TEST_USERS
        project, _ = setup_project_in_under_review(api, pi_id="pi-app-3reviews",
                                                     n_reviews=3)
        admin = TEST_USERS["research_admin_headers"]
        resp = api.approve_project(project["id"], admin)
        data = validate_success(resp)
        assert data["status"] == "APPROVED"

    def test_approve_consensus_not_met(self, api):
        """PRD §3.1: "the count of reviews with recommendation set to APPROVE is strictly
        greater than the count of reviews with recommendation set to REJECT
        (otherwise ERR_REVIEW_CONSENSUS_NOT_MET)."

        Claim: with 2 REJECT and 1 APPROVE (3 reviews total), approve returns ERR_REVIEW_CONSENSUS_NOT_MET.
        """
        from test_helpers import setup_project_in_under_review, TEST_USERS
        project, _ = setup_project_in_under_review(api, pi_id="pi-no-consensus", n_reviews=0)
        append_peer_review(api, project["id"], recommendation="REJECT", reviewer_id="r1")
        append_peer_review(api, project["id"], recommendation="REJECT", reviewer_id="r2")
        append_peer_review(api, project["id"], recommendation="APPROVE", reviewer_id="r3")
        admin = TEST_USERS["research_admin_headers"]
        resp = api.approve_project(project["id"], admin)
        validate_error(resp, ApiErrorId.ERR_REVIEW_CONSENSUS_NOT_MET.value)

    def test_approve_mints_project_code(self, api):
        """PRD §3.1: "On approval, the system mints project_code and writes it to the
        project. The code is composed by extracting the four-digit calendar year from
        the current UTC time, mapping the project's funding_source to a three-letter
        abbreviation — NATIONAL to NTL, PROVINCIAL to PRV, ENTERPRISE to ENT, and
        INTERNAL to INT — and appending a four-digit zero-padded sequence number that
        increases monotonically per (year, source) pair starting at 0001."

        Claim: after approval, project_code is non-null and follows YYYY-NTL-NNNN format
        for a NATIONAL project.
        """
        project, _ = create_and_approve_project(api, pi_id="pi-mint", funding_source="NATIONAL")
        assert project["project_code"] is not None
        parts = project["project_code"].split("-")
        assert len(parts) == 3, f"Expected YYYY-NTL-NNNN, got {project['project_code']}"
        assert len(parts[0]) == 4 and parts[0].isdigit()
        assert parts[1] == "NTL"
        assert len(parts[2]) == 4 and parts[2].isdigit()
        assert int(parts[2]) >= 1

    def test_approve_cascades_to_budget_items(self, api):
        """PRD §3.1: "Approval also transitions every BudgetItem of the project from
        PENDING to APPROVED, copying each item's requested_amount into its approved_amount,
        refreshes the project's total_budget to the sum of those approved amounts, and
        appends one AuditLog row per approved budget item with action set to APPROVE."

        # difficulty: transitive_cascade/project_approve_cascades_through_budget_items_to_audit_log

        Claim: approving a project transitions every BudgetItem PENDING→APPROVED, copies
        requested_amount → approved_amount, sums total_budget, and emits N APPROVE audit-log rows.
        """
        from test_helpers import list_audit_logs
        project, items = create_and_approve_project(
            api,
            pi_id="pi-cascade-approve",
            funding_source="NATIONAL",
            budget_items=[("PERSONNEL", 500.00), ("EQUIPMENT", 1000.00), ("MATERIALS", 200.00)],
        )
        # Re-read to confirm state.
        for item in items:
            assert item["status"] == "APPROVED", \
                f"BudgetItem {item['id']} expected APPROVED, got {item['status']}"
            assert item["approved_amount"] == item["requested_amount"], \
                f"BudgetItem.approved_amount={item['approved_amount']} should equal requested_amount={item['requested_amount']}"
        # Project.total_budget == sum of approved amounts (500 + 1000 + 200 = 1700)
        assert project["total_budget"] == pytest.approx(1700.00, abs=0.01)
        # AuditLog: at least 3 rows with subject_type=BUDGET_ITEM and action=APPROVE
        item_ids = {it["id"] for it in items}
        all_logs = list_audit_logs(api)
        approve_logs = [l for l in all_logs
                         if l.get("subject_type") == "BUDGET_ITEM"
                         and l.get("action") == "APPROVE"
                         and l.get("subject_id") in item_ids]
        assert len(approve_logs) == 3, f"Expected 3 APPROVE audit logs for the 3 budget items, got {len(approve_logs)}"

    def test_reject_keeps_budget_items_pending(self, api):
        """PRD §3.1: "On rejection, all BudgetItem rows remain in PENDING — that is
        their terminal state for a rejected project — and no project code is minted."

        Claim: after reject, budget items remain PENDING and project_code is null.
        """
        from test_helpers import setup_project_in_under_review, TEST_USERS
        project, items = setup_project_in_under_review(api, pi_id="pi-reject", n_reviews=3)
        admin = TEST_USERS["research_admin_headers"]
        resp = api.reject_project(project["id"], admin)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        assert data.get("project_code") is None
        # Budget items still PENDING
        from test_helpers import get_budget_item
        for it in items:
            cur = get_budget_item(api, it["id"])
            assert cur["status"] == "PENDING", \
                f"After project reject, BudgetItem {it['id']} should remain PENDING, got {cur['status']}"


class TestProjectActivate:
    """PRD §3.1 activation."""

    def test_activate_before_planned_start_rejected(self, api):
        """PRD §3.1: "The activation precondition is temporal: the current server time
        must be at or after planned_start_date, otherwise the request is rejected with
        ERR_PROJECT_NOT_YET_STARTED."

        Claim: activate before planned_start_date returns ERR_PROJECT_NOT_YET_STARTED.
        """
        from test_helpers import TEST_USERS
        # Far-future start so we know now() < planned_start_date.
        project, _ = create_and_approve_project(
            api, pi_id="pi-activate-early",
            funding_source="NATIONAL",
            start_offset_days=365,  # 1-year-out start
            duration_days=365,
        )
        admin = TEST_USERS["research_admin_headers"]
        resp = api.activate_project(project["id"], admin)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_YET_STARTED.value)

    def test_activate_at_or_after_start(self, api):
        """PRD §3.1: "The activation precondition is temporal: the current server time
        must be at or after planned_start_date, otherwise the request is rejected with
        ERR_PROJECT_NOT_YET_STARTED."

        Claim: with now() >= planned_start_date, activate succeeds with status=ACTIVE.
        """
        project, _ = create_and_activate_project(api, pi_id="pi-activate-ok")
        assert project["status"] == "ACTIVE"


class TestBeginClosing:
    """PRD §3.3 begin-closing transition."""

    def test_begin_closing_locks_budget_items(self, api):
        """PRD §3.3: "On commit, the project's status advances to CLOSING and every
        BudgetItem belonging to the project transitions to LOCKED — no further
        BudgetAdjustment and no further Reimbursement may be created against the
        project once locked."

        Claim: begin-closing transitions project to CLOSING and items to LOCKED.
        """
        from test_helpers import setup_project_in_closing
        project, items = setup_project_in_closing(api, pi_id="pi-begin-close")
        assert project["status"] == "CLOSING"
        from test_helpers import get_budget_item
        for it in items:
            cur = get_budget_item(api, it["id"])
            assert cur["status"] == "LOCKED", f"Expected LOCKED, got {cur['status']}"

    def test_begin_closing_with_open_reimbursements_rejected(self, api):
        """PRD §3.3: "it requires that no reimbursement under the project remains in
        SUBMITTED or UNDER_REVIEW, otherwise the request is rejected with
        ERR_OPEN_REIMBURSEMENTS_EXIST."

        Claim: begin-closing while a SUBMITTED reimbursement exists returns ERR_OPEN_REIMBURSEMENTS_EXIST.
        """
        from test_helpers import create_and_submit_reimbursement, make_principal_investigator_headers
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-open-reim", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)])
        # Create a SUBMITTED reimbursement.
        create_and_submit_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.begin_closing(project["id"], headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_REIMBURSEMENTS_EXIST.value)

    def test_begin_closing_not_owner(self, api):
        """PRD §3.3: "the acting X-User-ID must equal principal_investigator_id, otherwise
        ERR_NOT_PROJECT_OWNER".

        Claim: begin-closing by a non-owner returns ERR_NOT_PROJECT_OWNER.
        """
        from test_helpers import make_principal_investigator_headers
        project, _ = setup_active_project_with_budget(api, pi_id="pi-real-owner-bc")
        wrong = make_principal_investigator_headers("pi-imposter-bc")
        resp = api.begin_closing(project["id"], wrong)
        validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_OWNER.value)
