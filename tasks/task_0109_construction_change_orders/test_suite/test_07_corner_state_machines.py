"""State-machine corner tests (Corner queue: state_machines section)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN,
    create_project, create_sov_line,
    setup_project_with_one_sov_line, setup_project_with_two_sov_lines,
    create_pay_application, add_pay_app_line, submit_pay_application,
    certify_pay_application,
    create_change_order, submit_change_order,
)
from test_helpers import fixtures as fx


class TestSubmitAlreadySubmittedPayApp:
    def test_resubmit_submitted_app_returns_invalid_state(self, api):
        """PRD §3.4: "When the Contractor submits a pay application it advances DRAFT →
        SUBMITTED, permitted only when it is DRAFT". PRD §3.4: "a wrong-state submit is
        ERR_INVALID_STATE."

        Design: Corner/state_machines/submit_already_submitted_pay_app_returns_invalid_state
        """
        project, sov1, pay_app = fx.setup_submitted_pay_app_one_line()
        resp = api.submit_pay_application(pay_app["id"], CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestSubmitPayAppWithNoLines:
    def test_submit_with_zero_lines_returns_invalid_state(self, api):
        """PRD §3.4: "it advances DRAFT → SUBMITTED, permitted only when it is DRAFT, at
        least one pay-app line exists for it, and no line overbills".

        Design: Corner/state_machines/submit_pay_app_with_no_lines_returns_invalid_state
        """
        project, sov1 = setup_project_with_one_sov_line()
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        resp = api.submit_pay_application(app["id"], CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestSubstantialCompletionBlockedByOpenPunchItem:
    def test_substantial_completion_with_open_punch_item_rejected(self, api):
        """PRD §3.7: "The Architect marks a project substantially complete, advancing
        ACTIVE → SUBSTANTIALLY_COMPLETE, only when every punch-list item on the project is
        VERIFIED — none left OPEN, READY_FOR_REVIEW, or REOPENED ... and at least one pay
        application on the project is CERTIFIED; otherwise ERR_INVALID_STATE."

        Design: Corner/state_machines/substantial_completion_blocked_by_open_punch_item
        """
        project, sov1 = setup_project_with_one_sov_line()
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app["id"], sov1["id"], 100_000)
        submit_pay_application(app["id"])
        certify_pay_application(app["id"])
        validate_success(
            api.create_punch_item(
                {"project_id": project["id"], "location": "Roof",
                 "description": "Flashing", "severity": "MAJOR"},
                ARCHITECT,
            ),
            201,
        )
        resp = api.substantial_completion_project(project["id"], ARCHITECT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["status"] == "ACTIVE"


class TestRfiAnswerSideEffect:
    def test_answer_sets_ball_in_court_contractor_and_stores_text(self, api):
        """PRD §3.5: "An architect answers an open RFI by supplying an answer; this advances
        it OPEN → ANSWERED, sets ball_in_court to CONTRACTOR, and stores the answer text."

        Design: Corner/state_machines/rfi_answer_sets_ball_in_court_contractor
        """
        project = create_project(500_000, name="RfiP")
        rfi = validate_success(
            api.create_rfi(
                {"project_id": project["id"], "subject": "Beam size",
                 "question": "W12 or W14?"},
                CONTRACTOR,
            ),
            201,
        )
        resp = api.answer_rfi(rfi["id"], {"answer": "Use W14."}, ARCHITECT)
        data = validate_success(resp, 200)
        assert data["status"] == "ANSWERED"
        assert data["ball_in_court"] == "CONTRACTOR"
        assert data["answer"] == "Use W14."


class TestSubmittalTerminalClosedLocked:
    def test_review_on_closed_submittal_returns_invalid_state(self, api):
        """PRD §3.5: "Review is only legal from PENDING; otherwise ERR_INVALID_STATE."

        Design: Corner/state_machines/submittal_terminal_closed_locked
        """
        project = create_project(500_000, name="SubTermP")
        sub = validate_success(
            api.create_submittal(
                {"project_id": project["id"], "spec_section": "05 12 00",
                 "title": "Steel shop drawings"},
                CONTRACTOR,
            ),
            201,
        )
        validate_success(
            api.review_submittal(sub["id"], {"decision": "APPROVED"}, ARCHITECT), 200
        )
        validate_success(api.close_submittal(sub["id"], ARCHITECT), 200)
        resp = api.review_submittal(sub["id"], {"decision": "APPROVED"}, ARCHITECT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestChangeOrderRejectNoLedgerMutation:
    def test_reject_leaves_revised_sum_unchanged(self, api):
        """PRD §3.2: "an owner may move it SUBMITTED → REJECTED whenever it is SUBMITTED,
        and this performs no schedule-of-values or project mutation whatsoever."

        Design: Corner/state_machines/change_order_reject_no_ledger_mutation
        """
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=150_000,
            line_edits=[{"action": "ADD", "item_no": "003", "description": "Extra",
                         "scheduled_value_delta_cents": 150_000}],
        )
        resp = api.reject_change_order(co["id"], OWNER)
        data = validate_success(resp, 200)
        assert data["status"] == "REJECTED"
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["revised_contract_sum_cents"] == 1000000  # unchanged.
