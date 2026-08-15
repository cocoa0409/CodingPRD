"""Vote challenges, inspector certification, segregation of duties, OCC on
signing, and the post-certification compensation cascade (PRD §3.8, §2.7)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_inspector_certification,
    setup_meeting_in_progress, setup_meeting_held, setup_certified_meeting,
    create_certification_draft, current_meeting_version,
    make_inspector_headers,
)


def _raise_challenge(api, meeting_id, vote_id, reason="Beneficial ownership dispute"):
    resp = api.create_vote_challenge(
        {"meeting_id": meeting_id, "vote_instruction_id": vote_id, "reason": reason},
        make_inspector_headers("insp-1"),
    )
    return validate_success(resp, 201)


class TestChallengeUpheldCascade:
    """Depth-4 chain from adjudicate(UPHELD): challenge ruled, vote
    invalidated, tabulation and quorum recomputed, DRAFT certification
    superseded."""

    def _setup(self, api):
        """MEETING_HELD (3000+1000 FOR of 8000 outstanding = 5000bp met);
        DRAFT certification by insp-1; OPEN challenge on the 1000-share vote."""
        ctx = setup_meeting_held(
            account_specs=[{"shares_held": 3000}, {"shares_held": 1000}],
            vote_specs=[{"account": 0, "choice": "FOR"}, {"account": 1, "choice": "FOR"}],
            outstanding_shares=8000,
        )
        m_id = ctx["meeting"]["id"]
        cert = create_certification_draft(m_id, creator_user_id="insp-1")
        challenge = _raise_challenge(api, m_id, ctx["votes"][1]["id"],
                                     reason="Vote bought by solicitation party")
        return ctx, cert, challenge

    def test_upheld_invalidates_vote_and_recomputes_tabulation(self, api, proxy_admin_headers):
        """PRD §3.8: "An `UPHELD` ruling invalidates the vote — the instruction
        moves `VALIDATED → INVALIDATED` — and the effect cascades outward: the
        proposal's tabulation is recomputed".

        Design: Difficulty/transitive_cascade/challenge_upheld_cascade_invalidates_vote_certification
        """
        ctx, cert, challenge = self._setup(api)
        ruled = api.adjudicate_challenge(
            challenge["id"],
            {"ruling": "UPHELD", "resolution_note": "Solicitation defect proven"},
            make_inspector_headers("insp-1"),
        )
        data = validate_success(ruled, 200)
        assert data["status"] == "UPHELD"
        vote = validate_success(api.get_vote_instruction(ctx["votes"][1]["id"], proxy_admin_headers), 200)
        assert vote["status"] == "INVALIDATED", "the upheld challenge invalidates the vote"
        tab = validate_success(
            api.get_tabulation(ctx["proposals"][0]["id"], proxy_admin_headers, variant="UNOFFICIAL"), 200
        )
        assert tab["for_votes"] == 3000, (
            f"invalidated vote excluded from tabulation: {tab['for_votes']} (was 4000)"
        )

    def test_upheld_recomputes_quorum_and_supersedes_draft_certification(self, api, proxy_admin_headers):
        """PRD §3.8: "the meeting's quorum is recomputed, and any `DRAFT` or
        `SIGNED` certification for the meeting is superseded".

        Design: Difficulty/transitive_cascade/challenge_upheld_cascade_invalidates_vote_certification
        """
        ctx, cert, challenge = self._setup(api)
        m_id = ctx["meeting"]["id"]
        validate_success(api.adjudicate_challenge(
            challenge["id"], {"ruling": "UPHELD"}, make_inspector_headers("insp-1")
        ), 200)
        quorum = validate_success(api.get_quorum(m_id, proxy_admin_headers, variant="FINAL"), 200)
        assert quorum["shares_present"] == 3000, (
            f"FINAL shares_present after invalidation: {quorum['shares_present']}"
        )
        assert quorum["quorum_met"] is False, "3750bp < 5000bp after the cascade"
        certification = validate_success(api.get_inspector_certification(cert["id"], proxy_admin_headers), 200)
        assert certification["status"] == "SUPERSEDED", (
            "the DRAFT certification is superseded by the adjudication"
        )


class TestCertificationBlockedByOpenChallenge:
    """InspectorCertification x VoteChallenge: creation is rejected while any
    challenge is OPEN and unblocked by an OVERRULED ruling."""

    def _setup_with_open_challenge(self, api):
        ctx = setup_meeting_held(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        challenge = _raise_challenge(api, m_id, ctx["votes"][0]["id"],
                                     reason="Chain-of-custody question")
        return ctx, challenge

    def test_certification_creation_rejected_while_challenge_open(self, api):
        """PRD §3.8: "An `InspectorOfElection` creates an
        **InspectorCertification** draft for a meeting that is `MEETING_HELD`
        with zero `OPEN` challenges (`ERR_UNRESOLVED_CHALLENGES` if any
        remain)".

        Design: Difficulty/cross_entity_state_dependency/certification_blocked_by_open_challenge_then_unblocked
        """
        ctx, challenge = self._setup_with_open_challenge(api)
        resp = api.create_inspector_certification(
            {"meeting_id": ctx["meeting"]["id"]}, make_inspector_headers("insp-1")
        )
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_CHALLENGES, 422)

    def test_certification_creation_unblocked_after_overruled(self, api):
        """PRD §3.8: "An `OVERRULED` ruling leaves the targeted instruction
        untouched."
        PRD §3.8: "Creation records the acting inspector's header identity in
        `created_by_user_id` and snapshots the final state of play:
        `final_quorum_met` and `final_quorum_pct_bp` from the `FINAL` quorum
        variant at that instant".

        Design: Difficulty/cross_entity_state_dependency/certification_blocked_by_open_challenge_then_unblocked
        """
        ctx, challenge = self._setup_with_open_challenge(api)
        m_id = ctx["meeting"]["id"]
        validate_success(api.adjudicate_challenge(
            challenge["id"],
            {"ruling": "OVERRULED", "resolution_note": "Chain of custody intact"},
            make_inspector_headers("insp-1"),
        ), 200)
        resp = api.create_inspector_certification({"meeting_id": m_id}, make_inspector_headers("insp-1"))
        data = validate_success(resp, 201)
        assert_inspector_certification(data)
        assert data["status"] == "DRAFT"
        assert data["final_quorum_met"] is True, (
            "6000/10000 = 6000bp >= 5000bp with the OVERRULED vote back in the FINAL input set"
        )
        assert data["created_by_user_id"] == "insp-1"


class TestSegregationOfDutiesPriorityPair:
    """SoD (priority 5) is reported before the unresolved-challenges domain
    constraint (priority 8) when both fail."""

    def _setup_held_with_cert(self):
        ctx = setup_meeting_held(vote_specs=[{"account": 0, "choice": "FOR"}])
        cert = create_certification_draft(ctx["meeting"]["id"], creator_user_id="insp-1")
        return ctx, cert

    def test_sign_as_creator_with_open_challenge_reports_sod(self, api):
        """PRD §2.6: "5. **Segregation of duties.** The certification signer's
        conflict-of-interest check (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.6: "8. **Domain constraints.** Uniqueness, control-number,
        share-range, choice-compatibility, mode-compatibility, overlap, gating,
        and quorum rules (the specific error codes named in §3)".
        PRD §3.8: "a signer whose identity equals `created_by_user_id` is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/sign_sod_trumps_unresolved_challenges_constraint
        """
        ctx, cert = self._setup_held_with_cert()
        m_id = ctx["meeting"]["id"]
        # An OPEN challenge raised AFTER the draft means both rules fail.
        _raise_challenge(api, m_id, ctx["votes"][0]["id"], reason="Post-certification challenge")
        version = current_meeting_version(m_id)
        resp = api.sign_certification(
            cert["id"], {"expected_meeting_version": version}, make_inspector_headers("insp-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    def test_sign_as_creator_alone_reports_sod(self, api):
        """PRD §3.8: "The signer must be an `InspectorOfElection` other than
        the draft's creator — a signer whose identity equals
        `created_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/sign_sod_trumps_unresolved_challenges_constraint
        """
        ctx, cert = self._setup_held_with_cert()
        m_id = ctx["meeting"]["id"]
        version = current_meeting_version(m_id)
        resp = api.sign_certification(
            cert["id"], {"expected_meeting_version": version}, make_inspector_headers("insp-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)


class TestChallengeAndCertificationStateRules:
    def test_adjudicate_ruled_challenge_returns_challenge_not_open(self, api, proxy_admin_headers):
        """PRD §3.8: "only an `OPEN` challenge can be ruled on, otherwise
        `ERR_CHALLENGE_NOT_OPEN`."

        Design: Corner/state_machines/adjudicate_ruled_challenge_returns_challenge_not_open
        """
        ctx = setup_meeting_in_progress(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        challenge = _raise_challenge(api, m_id, ctx["votes"][0]["id"], reason="Duplicate ballot suspected")
        validate_success(api.adjudicate_challenge(
            challenge["id"], {"ruling": "UPHELD"}, make_inspector_headers("insp-1")
        ), 200)
        resp = api.adjudicate_challenge(
            challenge["id"], {"ruling": "OVERRULED"}, make_inspector_headers("insp-1")
        )
        validate_error(resp, ApiErrorId.ERR_CHALLENGE_NOT_OPEN, 409)
        current = validate_success(api.get_vote_challenge(challenge["id"], proxy_admin_headers), 200)
        assert current["status"] == "UPHELD", "rulings are final"

    def test_sign_superseded_certification_returns_certification_not_draft(self, api, proxy_admin_headers):
        """PRD §3.8: "creating a new draft supersedes any existing `DRAFT`
        certification for the meeting."
        PRD §3.8: "The certification must still be in `DRAFT`
        (`ERR_CERTIFICATION_NOT_DRAFT`)".

        Design: Corner/state_machines/sign_superseded_certification_returns_certification_not_draft
        """
        ctx = setup_meeting_held(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        cert1 = create_certification_draft(m_id, creator_user_id="insp-1")
        create_certification_draft(m_id, creator_user_id="insp-1")
        first = validate_success(api.get_inspector_certification(cert1["id"], proxy_admin_headers), 200)
        assert first["status"] == "SUPERSEDED", "the second draft supersedes the first"
        version = current_meeting_version(m_id)
        resp = api.sign_certification(
            cert1["id"], {"expected_meeting_version": version}, make_inspector_headers("insp-2")
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_DRAFT, 409)

    def test_certification_sign_stale_version_rejected(self, api, proxy_admin_headers):
        """PRD §2.7: "Signing an inspector certification. The same comparison
        is made against the meeting's current `version`; a mismatch is rejected
        with `ERR_STALE_VERSION` (HTTP 412), preventing the signer from
        certifying against a meeting state it has not observed."

        Design: Corner/cross_cutting_layers/certification_sign_stale_version_rejected
        """
        ctx = setup_meeting_held(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        cert = create_certification_draft(m_id, creator_user_id="insp-1")
        version = current_meeting_version(m_id)
        resp = api.sign_certification(
            cert["id"], {"expected_meeting_version": version - 1}, make_inspector_headers("insp-2")
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        certification = validate_success(api.get_inspector_certification(cert["id"], proxy_admin_headers), 200)
        assert certification["status"] == "DRAFT", "rejected signing leaves the draft untouched"
        meeting = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert meeting["status"] == "MEETING_HELD"


class TestPostCertificationCompensation:
    def test_adjudication_after_sign_reverts_meeting_and_proposals(self, api, proxy_admin_headers):
        """PRD §3.8: "if the superseded certification was `SIGNED`, the meeting
        itself reverts `RESULTS_CERTIFIED → MEETING_HELD` and all of its
        `PASSED` and `FAILED` proposals return to `ACTIVE`. This cascade is the
        intended compensation path when a late challenge upends certified
        results."
        PRD §3.8: "Once a meeting is in `MEETING_IN_PROGRESS`, `MEETING_HELD`,
        or `RESULTS_CERTIFIED`, the `InspectorOfElection` may contest
        individual ballots."

        Design: Corner/state_machines/adjudication_after_sign_reverts_meeting_and_proposals
        """
        ctx = setup_certified_meeting(vote_specs=[{"account": 0, "choice": "FOR"}])
        m_id = ctx["meeting"]["id"]
        proposal = ctx["proposals"][0]
        vote = ctx["votes"][0]
        cert = ctx["certification"]
        assert ctx["meeting"]["status"] == "RESULTS_CERTIFIED"
        challenge = _raise_challenge(api, m_id, vote["id"], reason="Late-discovered solicitation defect")
        validate_success(api.adjudicate_challenge(
            challenge["id"], {"ruling": "UPHELD"}, make_inspector_headers("insp-1")
        ), 200)
        certification = validate_success(api.get_inspector_certification(cert["id"], proxy_admin_headers), 200)
        assert certification["status"] == "SUPERSEDED"
        meeting = validate_success(api.get_meeting(m_id, proxy_admin_headers), 200)
        assert meeting["status"] == "MEETING_HELD", "signed certification knocked out: meeting reverts"
        prop = validate_success(api.get_proposal(proposal["id"], proxy_admin_headers), 200)
        assert prop["status"] == "ACTIVE", "PASSED proposal returns to ACTIVE"
        invalidated = validate_success(api.get_vote_instruction(vote["id"], proxy_admin_headers), 200)
        assert invalidated["status"] == "INVALIDATED"
