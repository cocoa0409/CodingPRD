"""Question submission moderation: the RETURN/resubmit loop, terminal
moderation states, mode gating, and role exclusivity (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_question_submission,
    create_draft_meeting, add_account,
    setup_voting_open,
    add_proposal, lock_record_date, generate_distributions, open_voting,
    make_shareholder_headers,
)


def _submit(api, meeting_id, account, text="What is the comp plan?"):
    resp = api.create_question_submission(
        {"meeting_id": meeting_id, "account_id": account["id"], "question_text": text},
        make_shareholder_headers(account["id"]),
    )
    return validate_success(resp, 201)


class TestReturnResubmitLoop:
    """SUBMITTED -> RETURNED -> SUBMITTED -> APPROVED: a cyclic machine with
    text replacement and note clearing on re-entry."""

    def test_return_stores_note_and_blocks_until_resubmitted(self, api, proxy_admin_headers):
        """PRD §3.5: "The `ProxyAdministrator` moderates each `SUBMITTED`
        question with an `action` of `APPROVE`, `REJECT`, or `RETURN` and an
        optional `moderation_note`, which is stored on the question; the
        question moves to `APPROVED`, `REJECTED`, or `RETURNED` accordingly".
        PRD §3.5: "A new question starts in `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/question_return_resubmit_moderation_loop
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account = ctx["accounts"][0]
        question = _submit(api, m_id, account)
        assert question["status"] == "SUBMITTED"
        returned = api.moderate_question(
            question["id"],
            {"action": "RETURN", "moderation_note": "Too broad; narrow to one item"},
            proxy_admin_headers,
        )
        data = validate_success(returned, 200)
        assert_question_submission(data)
        assert data["status"] == "RETURNED"
        assert data["moderation_note"] == "Too broad; narrow to one item", (
            "the moderation note is stored on the question"
        )

    def test_resubmit_replaces_text_clears_note_then_approves(self, api, proxy_admin_headers):
        """PRD §3.5: "A `RETURNED` question is not dead: the shareholder may
        resubmit it with replacement `question_text`, which clears the
        `moderation_note` back to null and returns the question to
        `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/question_return_resubmit_moderation_loop
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account = ctx["accounts"][0]
        question = _submit(api, m_id, account)
        validate_success(api.moderate_question(
            question["id"],
            {"action": "RETURN", "moderation_note": "Too broad; narrow to one item"},
            proxy_admin_headers,
        ), 200)
        resubmitted = api.resubmit_question(
            question["id"], {"question_text": "What is the CEO pay ratio?"},
            make_shareholder_headers(account["id"]),
        )
        data = validate_success(resubmitted, 200)
        assert data["status"] == "SUBMITTED", "the loop re-enters SUBMITTED"
        assert data["question_text"] == "What is the CEO pay ratio?"
        assert data["moderation_note"] is None, "resubmission clears the moderation note"
        approved = api.moderate_question(
            question["id"], {"action": "APPROVE", "moderation_note": "Queued for Q&A"},
            proxy_admin_headers,
        )
        final = validate_success(approved, 200)
        assert final["status"] == "APPROVED", "APPROVED is the terminal moderation state"


class TestQuestionStateRules:
    def test_moderate_approved_question_returns_invalid_question_state(self, api, proxy_admin_headers):
        """PRD §3.5: "moderating a question that is no longer `SUBMITTED` fails
        with `ERR_INVALID_QUESTION_STATE`."

        Design: Corner/state_machines/moderate_approved_question_returns_invalid_question_state
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        question = _submit(api, m_id, ctx["accounts"][0], text="Dividend policy?")
        validate_success(api.moderate_question(
            question["id"], {"action": "APPROVE"}, proxy_admin_headers
        ), 200)
        resp = api.moderate_question(question["id"], {"action": "REJECT"}, proxy_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_QUESTION_STATE, 409)
        current = validate_success(api.get_question_submission(question["id"], proxy_admin_headers), 200)
        assert current["status"] == "APPROVED", "question must remain APPROVED"

    def test_question_on_in_person_meeting_returns_mode_incompatible(self, api):
        """PRD §3.5: "submission is accepted only for `VIRTUAL` or `HYBRID`
        meetings (`ERR_MEETING_MODE_INCOMPATIBLE` otherwise)".

        Design: Corner/validations/question_on_in_person_meeting_returns_mode_incompatible
        """
        meeting = create_draft_meeting(meeting_mode="IN_PERSON")
        m_id = meeting["id"]
        account = add_account(m_id, "A-1001")
        lock_record_date(m_id)
        add_proposal(m_id, 1)
        generate_distributions(m_id)
        open_voting(m_id)
        resp = api.create_question_submission(
            {"meeting_id": m_id, "account_id": account["id"], "question_text": "Floor question?"},
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_MODE_INCOMPATIBLE, 422)


class TestQuestionRbac:
    def test_inspector_cannot_moderate_questions(self, api, proxy_admin_headers, inspector_headers):
        """PRD §2.1: "`ProxyAdministrator` — proxy agent operations staff. Owns
        the meeting lifecycle (creation, amendment, record-date lock, opening
        voting, convening, adjournment, reconvening, conclusion, cancellation,
        and the 8-K filing), proxy material generation and delivery outcomes,
        agenda proposals and withdrawals, virtual platform sessions,
        solicitation campaigns, question moderation, in-person vote capture,
        and the test-driving clock."
        PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/inspector_cannot_moderate_questions
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        question = _submit(api, m_id, ctx["accounts"][0], text="Board attendance?")
        resp = api.moderate_question(question["id"], {"action": "APPROVE"}, inspector_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        current = validate_success(api.get_question_submission(question["id"], proxy_admin_headers), 200)
        assert current["status"] == "SUBMITTED", "a forbidden moderation attempt changes nothing"
