"""Vote capture gates and constraints: voting phase, control numbers, share
range, choice compatibility, channel-role matrix, and immediate consistency
(PRD §3.4, §2.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_vote_instruction,
    setup_voting_open, setup_meeting_in_progress, setup_materials_distributed,
    open_voting,
    make_shareholder_headers, make_broker_headers,
)


def _vote_payload(m_id, p_id, account, channel="INTERNET", choice="FOR",
                  control_number=None, shares_voted=None):
    payload = {
        "meeting_id": m_id,
        "proposal_id": p_id,
        "account_id": account["id"],
        "channel": channel,
        "choice": choice,
    }
    if control_number is not None:
        payload["control_number"] = control_number
    if shares_voted is not None:
        payload["shares_voted"] = shares_voted
    return payload


class TestVotingPhaseGate:
    """VoteInstruction x Meeting: only VOTING_OPEN / MEETING_IN_PROGRESS admit
    votes."""

    def test_vote_rejected_while_materials_distributed(self, api):
        """PRD §3.4: "Voting is accepted only while the meeting is in
        `VOTING_OPEN` or `MEETING_IN_PROGRESS`; attempts at any other time fail
        with `ERR_VOTING_NOT_OPEN`".

        Design: Difficulty/cross_entity_state_dependency/vote_requires_meeting_voting_open
        """
        ctx = setup_materials_distributed()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, control_number=account["control_number"]),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_NOT_OPEN, 409)

    def test_vote_accepted_after_open_voting(self, api, proxy_admin_headers):
        """PRD §3.4: "Voting is accepted only while the meeting is in
        `VOTING_OPEN` or `MEETING_IN_PROGRESS`"; "A successfully cast
        instruction starts in `VALIDATED`."

        Design: Difficulty/cross_entity_state_dependency/vote_requires_meeting_voting_open
        """
        ctx = setup_materials_distributed()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        payload = _vote_payload(m_id, proposal["id"], account, control_number=account["control_number"])
        headers = make_shareholder_headers(account["id"])
        validate_error(api.create_vote_instruction(payload, headers), ApiErrorId.ERR_VOTING_NOT_OPEN, 409)
        open_voting(m_id)
        data = validate_success(api.create_vote_instruction(payload, headers), 201)
        assert_vote_instruction(data)
        assert data["status"] == "VALIDATED", "identical payload succeeds once voting opens"


class TestVoteConstraints:
    def test_vote_with_wrong_control_number_returns_invalid_control_number(self, api, proxy_admin_headers):
        """PRD §3.4: "Remote-channel votes — `INTERNET`, `PHONE`, and `MAIL` —
        must carry the account's `control_number`, and a missing or mismatched
        number is rejected with `ERR_INVALID_CONTROL_NUMBER`".

        Design: Corner/validations/vote_with_wrong_control_number_returns_invalid_control_number
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, control_number="999999999999"),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CONTROL_NUMBER, 422)
        listed, meta = validate_paginated(api.list_vote_instructions(
            proxy_admin_headers, params={"meeting_id": m_id, "account_id": account["id"]}
        ))
        assert meta["total_count"] == 0, "a rejected vote must not persist any instruction"

    def test_shares_voted_exceeding_held_returns_shares_exceed_held(self, api):
        """PRD §3.4: "The `shares_voted` must be greater than zero and no more
        than the account's `shares_held`, with violations rejected as
        `ERR_SHARES_EXCEED_HELD`."

        Design: Corner/validations/shares_voted_exceeding_held_returns_shares_exceed_held
        """
        ctx = setup_voting_open(account_specs=[{"shares_held": 7000}], outstanding_shares=20000)
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account,
                          control_number=account["control_number"], shares_voted=7001),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SHARES_EXCEED_HELD, 422)

    def test_partial_ballot_shares_voted_less_than_held_accepted(self, api, proxy_admin_headers):
        """PRD §3.4: "an optional `shares_voted` (defaulting to the full
        `shares_held` of the account)" and "The `shares_voted` must be greater
        than zero and no more than the account's `shares_held`".
        PRD §3.7: "shares present are the sum of `shares_voted` across the
        meeting's `VALIDATED` instructions".

        Design: Corner/validations/partial_ballot_shares_voted_less_than_held_accepted
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account,
                          control_number=account["control_number"], shares_voted=2000),
            make_shareholder_headers(account["id"]),
        )
        data = validate_success(resp, 201)
        assert_vote_instruction(data)
        assert data["status"] == "VALIDATED"
        assert data["shares_voted"] == 2000, "a partial ballot of 2000 of 6000 is accepted"
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="PROVISIONAL"), 200)
        assert quorum["shares_present"] == 2000, "quorum counts only the voted shares"

    def test_withhold_choice_on_non_director_proposal_returns_choice_not_allowed(self, api):
        """PRD §3.4: "`FOR`, `AGAINST`, and `ABSTAIN` are available on
        non-director proposals, while a `DIRECTOR_ELECTION` proposal accepts
        only `FOR` or `WITHHOLD` — `WITHHOLD` on any other proposal type, or
        `AGAINST` or `ABSTAIN` on a director election, is rejected with
        `ERR_CHOICE_NOT_ALLOWED`."

        Design: Corner/validations/withhold_choice_on_non_director_proposal_returns_choice_not_allowed
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, choice="WITHHOLD",
                          control_number=account["control_number"]),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHOICE_NOT_ALLOWED, 422)


class TestAdjournedVotePriorityPair:
    """State (priority 4) beats the control-number domain constraint
    (priority 8) when both are violated."""

    def _setup_adjourned(self, api, proxy_admin_headers):
        ctx = setup_meeting_in_progress()
        m_id = ctx["meeting"]["id"]
        validate_success(api.adjourn(m_id, proxy_admin_headers), 200)
        return ctx

    def test_adjourned_vote_with_wrong_control_number_reports_state_error(self, api, proxy_admin_headers):
        """PRD §2.6: "the server applies them in a fixed precedence order so
        that the failure surfaced to the caller is deterministic".
        PRD §2.6: "4. **State.** Whether the target resource's lifecycle state
        permits the operation (`ERR_INVALID_MEETING_STATE` and its
        resource-specific counterparts)."
        PRD §2.6: "8. **Domain constraints.** Uniqueness, control-number,
        share-range, choice-compatibility, mode-compatibility, overlap, gating,
        and quorum rules (the specific error codes named in §3)".
        PRD §3.7: "vote and revoke calls during an adjournment fail with
        `ERR_VOTING_NOT_OPEN`".

        Design: Difficulty/priority_pair_validation_conflict/adjourned_vote_state_trumps_control_number_constraint
        """
        ctx = self._setup_adjourned(api, proxy_admin_headers)
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, control_number="000000000000"),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_NOT_OPEN, 409)

    def test_adjourned_vote_with_correct_control_number_reports_state_error(self, api, proxy_admin_headers):
        """PRD §3.7: "Adjourning moves the meeting from `MEETING_IN_PROGRESS`
        to `ADJOURNED` and suspends voting — vote and revoke calls during an
        adjournment fail with `ERR_VOTING_NOT_OPEN`".

        Design: Difficulty/priority_pair_validation_conflict/adjourned_vote_state_trumps_control_number_constraint
        """
        ctx = self._setup_adjourned(api, proxy_admin_headers)
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, control_number=account["control_number"]),
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_NOT_OPEN, 409)


class TestChannelRoleMatrix:
    def test_broker_channel_vote_role_matrix(self, api):
        """PRD §3.4: "The channel a caller may use is bound to its role: a
        `Shareholder` votes over `INTERNET`, `PHONE`, or `MAIL` and only on its
        own account; a `Broker` votes over the `BROKER` channel; and a
        `ProxyAdministrator` records `IN_PERSON` votes. A channel that does not
        match the caller's role, or a shareholder acting on another holder's
        account, is rejected with `ERR_FORBIDDEN`."
        PRD §3.4: "the `BROKER` channel is exempt from the control-number
        check."

        Design: Corner/rbac/broker_channel_vote_role_matrix
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        as_shareholder = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, channel="BROKER"),
            make_shareholder_headers(account["id"]),
        )
        validate_error(as_shareholder, ApiErrorId.ERR_FORBIDDEN, 403)
        as_broker = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, channel="BROKER"),
            make_broker_headers("broker-1"),
        )
        data = validate_success(as_broker, 201)
        assert_vote_instruction(data)
        assert data["status"] == "VALIDATED", (
            "a Broker-channel vote needs no control_number and succeeds"
        )


class TestImmediateConsistency:
    def test_vote_create_response_immediately_reflects_final_state(self, api, proxy_admin_headers):
        """PRD §2.5: "Every mutation is visible in the response of the call
        that performed it; derived rollups such as quorum and tabulation
        figures are recomputed whenever an underlying vote changes."
        PRD §3.4: "an optional `shares_voted` (defaulting to the full
        `shares_held` of the account)"; "A successfully cast instruction starts
        in `VALIDATED`."

        Design: Corner/consistency_model/vote_create_response_immediately_reflects_final_state
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        resp = api.create_vote_instruction(
            _vote_payload(m_id, proposal["id"], account, control_number=account["control_number"]),
            make_shareholder_headers(account["id"]),
        )
        created = validate_success(resp, 201)
        assert_vote_instruction(created)
        assert created["status"] == "VALIDATED"
        assert created["shares_voted"] == 6000, (
            "omitted shares_voted defaults to the full shares_held"
        )
        fetched = validate_success(api.get_vote_instruction(created["id"], proxy_admin_headers), 200)
        assert fetched["status"] == created["status"] == "VALIDATED"
        assert fetched["shares_voted"] == created["shares_voted"] == 6000
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="PROVISIONAL"), 200)
        assert quorum["shares_present"] == 6000, "quorum reflects the new vote with no lag"
