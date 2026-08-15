"""Vote revocation, supersession, and proposal withdrawal cascades
(PRD §3.4, §3.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    setup_voting_open,
    cast_vote,
    make_shareholder_headers,
)


def _setup_single_for_vote():
    """VOTING_OPEN meeting; a1 6000 COMMON has one VALIDATED FOR vote."""
    ctx = setup_voting_open()
    m_id = ctx["meeting"]["id"]
    vote = cast_vote(m_id, ctx["proposals"][0]["id"], ctx["accounts"][0], choice="FOR")
    return ctx, vote


class TestRevokeCascade:
    """Revoke causes VALIDATED -> REVOKED (link 1), then both the proposal
    tabulation and the meeting quorum recompute (link 2)."""

    def test_revoke_recomputes_tabulation(self, api, proxy_admin_headers):
        """PRD §3.4: "A holder (its own votes only) or the administrator may
        also explicitly revoke a `VALIDATED` instruction while the meeting is
        in `VOTING_OPEN` or `MEETING_IN_PROGRESS`, moving it to `REVOKED`";
        "Supersession, revocation, invalidation, and proposal withdrawal each
        trigger recomputation of the affected proposal's tabulation and the
        meeting's quorum."

        Design: Difficulty/transitive_cascade/vote_revoke_cascade_recomputes_tabulation_and_quorum
        """
        ctx, vote = _setup_single_for_vote()
        p_id = ctx["proposals"][0]["id"]
        revoked = api.revoke_vote(vote["id"], make_shareholder_headers(ctx["accounts"][0]["id"]))
        data = validate_success(revoked, 200)
        assert data["status"] == "REVOKED", f"expected REVOKED, got {data['status']}"
        tab = validate_success(api.get_tabulation(p_id, proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert tab["for_votes"] == 0 and tab["votes_cast"] == 0, (
            f"revoked vote leaves the tabulation empty: {tab['for_votes']}/{tab['votes_cast']}"
        )

    def test_revoke_recomputes_quorum(self, api, proxy_admin_headers):
        """PRD §3.4: "Supersession, revocation, invalidation, and proposal
        withdrawal each trigger recomputation of the affected proposal's
        tabulation and the meeting's quorum."
        PRD §3.7: "For the `PROVISIONAL` variant, shares present are the sum of
        `shares_voted` across the meeting's `VALIDATED` instructions".

        Design: Difficulty/transitive_cascade/vote_revoke_cascade_recomputes_tabulation_and_quorum
        """
        ctx, vote = _setup_single_for_vote()
        m_id = ctx["meeting"]["id"]
        validate_success(api.revoke_vote(vote["id"], make_shareholder_headers(ctx["accounts"][0]["id"])), 200)
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="PROVISIONAL"), 200)
        assert quorum["shares_present"] == 0, (
            f"REVOKED votes drop out of shares_present: {quorum['shares_present']}"
        )
        assert quorum["quorum_met"] is False


class TestSupersedeAndRevokeRules:
    def test_revoke_superseded_vote_returns_vote_not_alterable(self, api, proxy_admin_headers):
        """PRD §3.4: "If a newer valid instruction arrives for the same account
        and proposal, the older one transitions `VALIDATED → SUPERSEDED`
        automatically, so at most one instruction per account-and-proposal is
        live."
        PRD §3.4: "revoking an instruction that is already `SUPERSEDED`,
        `REVOKED`, or `INVALIDATED` is rejected with `ERR_VOTE_NOT_ALTERABLE`."

        Design: Corner/state_machines/revoke_superseded_vote_returns_vote_not_alterable
        """
        ctx = setup_voting_open()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        v1 = cast_vote(m_id, proposal["id"], account, choice="FOR", channel="INTERNET")
        v2 = cast_vote(m_id, proposal["id"], account, choice="AGAINST", channel="PHONE")
        first = validate_success(api.get_vote_instruction(v1["id"], proxy_admin_headers), 200)
        assert first["status"] == "SUPERSEDED", "latest valid vote wins"
        second = validate_success(api.get_vote_instruction(v2["id"], proxy_admin_headers), 200)
        assert second["status"] == "VALIDATED"
        resp = api.revoke_vote(v1["id"], make_shareholder_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_VOTE_NOT_ALTERABLE, 409)

    def test_vote_on_withdrawn_proposal_returns_proposal_not_active(self, api, proxy_admin_headers):
        """PRD §3.4: "withdrawing an `ACTIVE` proposal also supersedes every
        `VALIDATED` vote instruction on it and triggers recomputation of the
        proposal's tabulation and the meeting's quorum."
        PRD §3.4: "a vote against a proposal that is not `ACTIVE` fails with
        `ERR_PROPOSAL_NOT_ACTIVE`."

        Design: Corner/state_machines/vote_on_withdrawn_proposal_returns_proposal_not_active
        """
        ctx, vote = _setup_single_for_vote()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        withdrawn = api.withdraw_proposal(proposal["id"], proxy_admin_headers)
        data = validate_success(withdrawn, 200)
        assert data["status"] == "WITHDRAWN"
        superseded = validate_success(api.get_vote_instruction(vote["id"], proxy_admin_headers), 200)
        assert superseded["status"] == "SUPERSEDED", (
            "withdrawal supersedes the proposal's VALIDATED votes"
        )
        resp = api.create_vote_instruction(
            {
                "meeting_id": m_id,
                "proposal_id": proposal["id"],
                "account_id": account["id"],
                "channel": "INTERNET",
                "choice": "AGAINST",
                "control_number": account["control_number"],
            },
            make_shareholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_ACTIVE, 409)


class TestRevokeRevoteInvariant:
    """The conserved quantity: weighted totals and shares_present. A revoke
    followed by an identical re-vote must restore them with no drift."""

    def test_revote_restores_tabulation_totals(self, api, proxy_admin_headers):
        """PRD §3.4: "A holder (its own votes only) or the administrator may
        also explicitly revoke a `VALIDATED` instruction while the meeting is
        in `VOTING_OPEN` or `MEETING_IN_PROGRESS`, moving it to `REVOKED`".
        PRD §3.4: "If a newer valid instruction arrives for the same account
        and proposal, the older one transitions `VALIDATED → SUPERSEDED`
        automatically, so at most one instruction per account-and-proposal is
        live."

        Design: Difficulty/compensating_invariant/revoke_then_identical_revote_restores_tabulation_totals
        """
        ctx, v1 = _setup_single_for_vote()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        validate_success(api.revoke_vote(v1["id"], make_shareholder_headers(account["id"])), 200)
        v2 = cast_vote(m_id, proposal["id"], account, choice="FOR", channel="INTERNET")
        assert v2["status"] == "VALIDATED"
        old = validate_success(api.get_vote_instruction(v1["id"], proxy_admin_headers), 200)
        assert old["status"] == "REVOKED"
        tab = validate_success(api.get_tabulation(proposal["id"], proxy_admin_headers, variant="UNOFFICIAL"), 200)
        assert tab["for_votes"] == 6000, (
            f"identical re-vote restores for_votes to 6000, got {tab['for_votes']}"
        )

    def test_revote_restores_quorum_and_single_live_instruction(self, api, proxy_admin_headers):
        """PRD §3.4: "at most one instruction per account-and-proposal is
        live."
        PRD §3.7: "shares present are the sum of `shares_voted` across the
        meeting's `VALIDATED` instructions".
        PRD §2.3: "vote instructions by `meeting_id`, `proposal_id`,
        `account_id`, `channel`, and `status`".

        Design: Difficulty/compensating_invariant/revoke_then_identical_revote_restores_tabulation_totals
        """
        ctx, v1 = _setup_single_for_vote()
        m_id = ctx["meeting"]["id"]
        account, proposal = ctx["accounts"][0], ctx["proposals"][0]
        validate_success(api.revoke_vote(v1["id"], make_shareholder_headers(account["id"])), 200)
        cast_vote(m_id, proposal["id"], account, choice="FOR", channel="INTERNET")
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="PROVISIONAL"), 200)
        assert quorum["shares_present"] == 6000, (
            f"shares_present returns to its pre-revoke value: {quorum['shares_present']}"
        )
        listed, meta = validate_paginated(api.list_vote_instructions(
            proxy_admin_headers,
            params={"meeting_id": m_id, "account_id": account["id"], "status": "VALIDATED"},
        ))
        assert meta["total_count"] == 1, (
            f"exactly one live instruction per account+proposal, got {meta['total_count']}"
        )
