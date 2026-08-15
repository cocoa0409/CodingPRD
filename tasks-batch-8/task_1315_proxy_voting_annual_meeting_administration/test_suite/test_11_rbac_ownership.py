"""Role-based access control and shareholder ownership scoping (PRD §2.1)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_draft_meeting, add_account,
    setup_voting_open, setup_meeting_in_progress,
    create_meeting_payload, create_shareholder_account_payload,
    make_shareholder_headers,
    TEST_USERS,
)


class TestRoleDenial:
    def test_shareholder_cannot_create_meeting(self, api, shareholder_headers):
        """PRD §2.1: "`ProxyAdministrator` — proxy agent operations staff. Owns
        the meeting lifecycle (creation, amendment, record-date lock, opening
        voting, convening, adjournment, reconvening, conclusion, cancellation,
        and the 8-K filing), proxy material generation and delivery outcomes,
        agenda proposals and withdrawals, virtual platform sessions,
        solicitation campaigns, question moderation, in-person vote capture,
        and the test-driving clock."
        PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/shareholder_cannot_create_meeting
        """
        resp = api.create_meeting(create_meeting_payload(), shareholder_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_broker_cannot_create_shareholder_accounts(self, api, broker_headers):
        """PRD §2.1: "`TransferAgent` — the issuer's transfer agent. Builds the
        record-date shareholder list and initiates broker searches".
        PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/broker_cannot_create_shareholder_accounts
        """
        meeting = create_draft_meeting()
        resp = api.create_shareholder_account(
            create_shareholder_account_payload(meeting["id"], "A-1001"), broker_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_transfer_agent_cannot_adjudicate_challenges(self, api, transfer_agent_headers, proxy_admin_headers):
        """PRD §2.1: "`InspectorOfElection` — the independent inspector. Raises
        and adjudicates vote challenges, and creates and signs result
        certifications."
        PRD §2.1: "A request whose role is not permitted to perform the
        requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/transfer_agent_cannot_adjudicate_challenges
        """
        ctx = setup_meeting_in_progress(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        resp = api.create_vote_challenge(
            {"meeting_id": m_id, "vote_instruction_id": ctx["votes"][0]["id"],
             "reason": "Suspect ballot"},
            TEST_USERS["inspector_headers"],
        )
        challenge = validate_success(resp, 201)
        denied = api.adjudicate_challenge(challenge["id"], {"ruling": "UPHELD"}, transfer_agent_headers)
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN, 403)
        current = validate_success(api.get_vote_challenge(challenge["id"], proxy_admin_headers), 200)
        assert current["status"] == "OPEN", "a forbidden adjudication changes nothing"


class TestShareholderOwnership:
    def test_shareholder_cannot_vote_on_other_account(self, api):
        """PRD §2.1: "ownership checks on any resource that references a
        shareholder account — the account itself, a vote instruction, or a
        question submission — compare the resource's account foreign-key field
        to `X-User-ID`."
        PRD §3.4: "a shareholder acting on another holder's account, is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/shareholder_cannot_vote_on_other_account
        """
        ctx = setup_voting_open(account_specs=[{"shares_held": 6000}, {"shares_held": 4000}])
        m_id = ctx["meeting"]["id"]
        a1, a2 = ctx["accounts"][0], ctx["accounts"][1]
        proposal = ctx["proposals"][0]
        resp = api.create_vote_instruction(
            {
                "meeting_id": m_id,
                "proposal_id": proposal["id"],
                "account_id": a2["id"],
                "channel": "INTERNET",
                "choice": "FOR",
                "control_number": a2["control_number"],
            },
            make_shareholder_headers(a1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_shareholder_cannot_read_other_account(self, api):
        """PRD §2.1: "A `Shareholder` may therefore read only its own account
        record, its own votes, and its own questions, and may act only on
        resources tied to its own account."

        Design: Corner/rbac/shareholder_cannot_read_other_account
        """
        meeting = create_draft_meeting()
        a1 = add_account(meeting["id"], "A-1001", shares_held=6000)
        a2 = add_account(meeting["id"], "A-1002", shares_held=4000)
        denied = api.get_shareholder_account(a2["id"], make_shareholder_headers(a1["id"]))
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN, 403)
        own = api.get_shareholder_account(a1["id"], make_shareholder_headers(a1["id"]))
        data = validate_success(own, 200)
        assert data["id"] == a1["id"], "reading one's own account record succeeds"
