"""Modification requests, consent votes, tallies, thresholds, and
re-solicitation cycles (PRD §2.6, §2.9, §3.6)."""
from test_helpers import (
    ApiErrorId,
    add_participant,
    api_client,
    cast_consent_vote,
    commit_participant,
    create_borrower,
    create_draw,
    create_facility,
    create_modification,
    create_modification_payload,
    get_consent_vote,
    get_facility,
    get_modification_request,
    get_success_data,
    make_agent_headers,
    make_borrower_headers,
    make_participant_headers,
    propose_transfer,
    set_clock,
    settle_transfer,
    settlement_for_participant,
    setup_funded_facility,
    solicit_modification,
    validate_error,
    validate_success,
    wire_and_confirm_due,
)

AGENT = make_agent_headers()

STANDARD_COMMITMENTS = [("P1", 6_000_000), ("P2", 3_000_000), ("P3", 1_000_000)]


def _solicited(commitments, draw_amount, modification_type, terms, total=None):
    """Funded facility + modification solicited at the default clock 2026-08-01
    (voting window closes 2026-08-16 with the 15-day default)."""
    setup = setup_funded_facility(commitments, draw_amount, total_commitment_cents=total)
    mod = create_modification(
        setup["facility"]["id"], setup["borrower"]["id"], modification_type, terms
    )
    solicit_modification(mod["id"])
    return setup, mod


class TestConsentThresholdBoundary:
    def test_consent_threshold_exact_boundary_pass_and_fail(self):
        """PRD §2.6: "Threshold comparisons for voting and consent outcomes are
        inclusive: a share exactly equal to the required threshold passes."
        PRD §3.6: "otherwise, if `approving_share_bps` meets or exceeds
        `required_threshold_bps`, it moves to `PASSED`; otherwise to `FAILED`.
        The threshold boundary is inclusive."

        Design: Difficulty/boundary_precision_check/consent_threshold_exact_boundary_pass_and_fail
        """
        # FacA: approving 5,001,000 of 10,000,000 -> exactly 5001 bps.
        setup_a, mod_a = _solicited(
            [("X", 5_001_000), ("Y", 4_999_000)], 1_000_000,
            "COVENANT_WAIVER", {"waiver_text": "A"},
        )
        xa = setup_a["participants"][0]
        cast_consent_vote(mod_a["id"], xa["id"], "APPROVE")

        # FacB: approving 5,000,500 -> floors to 5000 bps, one bp short.
        setup_b, mod_b = _solicited(
            [("X2", 5_000_500), ("Y2", 4_999_500)], 1_000_000,
            "COVENANT_WAIVER", {"waiver_text": "B"},
        )
        xb = setup_b["participants"][0]
        cast_consent_vote(mod_b["id"], xb["id"], "APPROVE")

        set_clock("2026-08-17T00:00:00Z")
        result_a = validate_success(api_client.tally_close_modification(mod_a["id"], AGENT))
        assert result_a["status"] == "PASSED"
        assert result_a["approving_share_bps"] == 5001

        result_b = validate_success(api_client.tally_close_modification(mod_b["id"], AGENT))
        assert result_b["status"] == "FAILED"
        assert result_b["approving_share_bps"] == 5000
        # Cast share meets the 5000 quorum exactly, so this FAILED (not EXPIRED).
        assert result_b["cast_share_bps"] == 5000

    def test_supermajority_threshold_exact_boundary_passes(self):
        """PRD §2.6: "Threshold comparisons for voting and consent outcomes are
        inclusive: a share exactly equal to the required threshold passes."
        PRD §3.6: "The system derives the consent class from the type and stores
        it in `required_consent_class`: `COMMITMENT_INCREASE` and
        `COVENANT_WAIVER` require a `MAJORITY`, `RATE_CHANGE` and
        `MATURITY_EXTENSION` require a `SUPERMAJORITY`, and
        `PRINCIPAL_WRITE_DOWN` and `BORROWER_SUBSTITUTION` require a `UNANIMOUS`
        consent."

        Design: Difficulty/boundary_precision_check/consent_threshold_exact_boundary_pass_and_fail
        """
        setup, mod = _solicited(
            [("X", 6_667_000), ("Y", 3_333_000)], 1_000_000,
            "RATE_CHANGE", {"new_interest_rate_bps": 1100},
        )
        assert mod["required_consent_class"] == "SUPERMAJORITY"
        assert mod["required_threshold_bps"] == 6667
        x = setup["participants"][0]
        cast_consent_vote(mod["id"], x["id"], "APPROVE")

        set_clock("2026-08-17T00:00:00Z")
        result = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        # floor(10000 * 6,667,000 / 10,000,000) == 6667: exactly at threshold.
        assert result["approving_share_bps"] == 6667
        assert result["status"] == "PASSED"


class TestTallyAggregation:
    def test_modification_tally_depends_on_vote_aggregation(self):
        """PRD §3.6: "`approving_commitment_cents` sums the commitments of
        participants whose current vote is `APPROVE`; `cast_commitment_cents`
        sums the commitments behind any current vote, including `ABSTAIN`."
        PRD §3.6: "otherwise, if `approving_share_bps` meets or exceeds
        `required_threshold_bps`, it moves to `PASSED`; otherwise to `FAILED`."

        Design: Difficulty/cross_entity_state_dependency/modification_tally_depends_on_vote_aggregation
        """
        setup, mod = _solicited(
            STANDARD_COMMITMENTS, 1_000_000, "COVENANT_WAIVER", {"waiver_text": "T"}
        )
        p1, p2, _ = setup["participants"]
        cast_consent_vote(mod["id"], p1["id"], "ABSTAIN")
        cast_consent_vote(mod["id"], p2["id"], "APPROVE")

        set_clock("2026-08-17T00:00:00Z")
        result = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        # ABSTAIN counts toward the cast share (quorum) but not approval.
        assert result["approving_commitment_cents"] == 3_000_000
        assert result["cast_commitment_cents"] == 9_000_000
        assert result["approving_share_bps"] == 3000
        assert result["cast_share_bps"] == 9000
        assert result["status"] == "FAILED"

    def test_reject_counts_toward_cast_but_not_approving(self):
        """PRD §3.6: "`approving_commitment_cents` sums the commitments of
        participants whose current vote is `APPROVE`; `cast_commitment_cents`
        sums the commitments behind any current vote, including `ABSTAIN`."

        Design: Difficulty/cross_entity_state_dependency/modification_tally_depends_on_vote_aggregation
        """
        setup, mod = _solicited(
            STANDARD_COMMITMENTS, 1_000_000, "COVENANT_WAIVER", {"waiver_text": "T"}
        )
        p1, p2, _ = setup["participants"]
        cast_consent_vote(mod["id"], p1["id"], "REJECT")
        cast_consent_vote(mod["id"], p2["id"], "APPROVE")

        set_clock("2026-08-17T00:00:00Z")
        result = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        assert result["approving_share_bps"] == 3000
        assert result["cast_share_bps"] == 9000
        assert result["status"] == "FAILED"


class TestRecastAndResolicitation:
    def test_consent_recast_and_resolicitation_cycles(self):
        """PRD §3.6: "Recasting — `CAST` → `RECAST`, and a self-loop from
        `RECAST` to `RECAST` — carries the same ownership, eligibility, state,
        and window rules, replaces the `vote`, increments `recast_count`,
        refreshes `cast_at`, and recomputes the tallies."
        PRD §3.6: "Solicitation is permitted from `DRAFT` and again from `FAILED`
        or `EXPIRED` as a re-solicitation cycle". "On a re-solicitation, every
        vote from the prior round is voided into `VOIDED` and a fresh window and
        base snapshot are taken."

        Design: Difficulty/non_linear_state_machine/consent_recast_and_resolicitation_cycles
        """
        setup, mod = _solicited(
            STANDARD_COMMITMENTS, 1_000_000, "RATE_CHANGE", {"new_interest_rate_bps": 1100}
        )
        facility = setup["facility"]
        p1, p2, _ = setup["participants"]

        v1 = cast_consent_vote(mod["id"], p1["id"], "APPROVE")
        validate_success(
            api_client.recast_consent_vote(
                v1["id"], {"vote": "REJECT"}, make_participant_headers(p1["id"])
            )
        )
        recast2 = validate_success(
            api_client.recast_consent_vote(
                v1["id"], {"vote": "APPROVE"}, make_participant_headers(p1["id"])
            )
        )
        assert recast2["recast_count"] == 2
        assert recast2["status"] == "RECAST"
        cast_consent_vote(mod["id"], p2["id"], "ABSTAIN")

        # Round 1: approving 6000 < 6667 with cast 9000 >= quorum 5000 -> FAILED.
        set_clock("2026-08-17T00:00:00Z")
        tally1 = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        assert tally1["status"] == "FAILED"

        # Re-solicit: prior-round votes are voided, a fresh window opens.
        set_clock("2026-08-18T00:00:00Z")
        validate_success(api_client.solicit_modification(mod["id"], AGENT))
        assert get_consent_vote(v1["id"])["status"] == "VOIDED"

        cast_consent_vote(mod["id"], p1["id"], "APPROVE")
        cast_consent_vote(mod["id"], p2["id"], "APPROVE")
        set_clock("2026-09-03T00:00:00Z")
        tally2 = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        assert tally2["status"] == "PASSED"
        assert tally2["approving_share_bps"] == 9000

        implemented = validate_success(api_client.implement_modification(mod["id"], AGENT))
        assert implemented["status"] == "IMPLEMENTED"
        assert get_facility(facility["id"])["interest_rate_bps"] == 1100

    def test_recast_ownership_and_window_rules(self):
        """PRD §2.1: "Reporting a wire on another participant's settlement,
        recasting another participant's vote, cancelling another participant's
        transfer, or rescinding another participant's demand is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §3.6: "Recasting — `CAST` → `RECAST`, and a self-loop from `RECAST`
        to `RECAST` — carries the same ownership, eligibility, state, and window
        rules".

        Design: Difficulty/non_linear_state_machine/consent_recast_and_resolicitation_cycles
        """
        setup, mod = _solicited(
            STANDARD_COMMITMENTS, 1_000_000, "COVENANT_WAIVER", {"waiver_text": "T"}
        )
        p1, p2, _ = setup["participants"]
        v1 = cast_consent_vote(mod["id"], p1["id"], "APPROVE")

        # Another participant cannot recast P1's vote.
        resp = api_client.recast_consent_vote(
            v1["id"], {"vote": "REJECT"}, make_participant_headers(p2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

        # The owner cannot recast once the window has closed.
        set_clock("2026-08-17T00:00:00Z")
        resp2 = api_client.recast_consent_vote(
            v1["id"], {"vote": "REJECT"}, make_participant_headers(p1["id"])
        )
        validate_error(resp2, ApiErrorId.ERR_VOTING_CLOSED, expected_status=409)


class TestVoterEligibilityPriority:
    def test_exited_participant_vote_beats_voting_window_close(self):
        """PRD §2.9: "When several validations could reject the same request, the
        server evaluates them in the following fixed priority order and returns
        the error from the first failing check only".
        PRD §2.9: "11. Referenced-party eligibility: voters must be `FUNDED`
        participants of the facility, transferors must be `COMMITTED` or
        `FUNDED`, wire reporters must be the settlement's own participant,
        buyback demanders must be `FUNDED`, an attached statement must belong to
        the facility and be received, and implementation requires a passed
        solicitation — otherwise `ERR_PARTICIPANT_NOT_ELIGIBLE`,
        `ERR_STATEMENT_NOT_RECEIVED`, `ERR_MODIFICATION_NOT_PASSED`, or
        `ERR_BUYBACK_NOT_FUNDED`."
        PRD §2.9: "12. Temporal gates: votes only while a solicitation is open
        and before its close, tallies only after the close, default-marking only
        after the funding due date, and transfer settlement dates outside payment
        blackout windows — otherwise `ERR_VOTING_CLOSED`,
        `ERR_VOTING_STILL_OPEN`, `ERR_FUNDING_NOT_YET_DUE`, or
        `ERR_SETTLEMENT_IN_BLACKOUT`."

        Design: Difficulty/priority_pair_validation_conflict/exited_participant_vote_beats_voting_window_close
        """
        setup = setup_funded_facility(STANDARD_COMMITMENTS, 1_000_000)
        facility = setup["facility"]
        borrower = setup["borrower"]
        _, _, p3 = setup["participants"]

        # P3 exits fully via transfer to a new entrant before the solicitation.
        transfer = propose_transfer(
            facility["id"], p3["id"], 1_000_000, "2026-08-10",
            transferee_name="P4 Bank",
        )
        settle_transfer(transfer["id"], p3["id"])
        assert setup["participants"][2]["id"] == p3["id"]
        assert api_client.get_participant(p3["id"], AGENT).json()["data"]["status"] == "EXITED"

        mod = create_modification(
            facility["id"], borrower["id"], "COVENANT_WAIVER",
            {"waiver_text": "Waive coverage ratio"},
        )
        set_clock("2026-08-18T00:00:00Z")
        solicit_modification(mod["id"])

        # Window closed 2026-09-02; the EXITED voter hits the eligibility rule
        # (priority 11) even though the temporal rule (12) also fails.
        set_clock("2026-09-03T00:00:00Z")
        resp = api_client.cast_consent_vote(
            mod["id"], {"vote": "APPROVE"}, make_participant_headers(p3["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE, expected_status=409)

    def test_unfunded_participant_vote_rejected_while_window_open(self):
        """PRD §3.6: "Casting requires the caller to be a `FUNDED` participant of
        the facility, failing `ERR_PARTICIPANT_NOT_ELIGIBLE`".

        Design: Difficulty/priority_pair_validation_conflict/exited_participant_vote_beats_voting_window_close
        """
        borrower = create_borrower()
        facility = create_facility(borrower["id"], total_commitment_cents=10_000_000)
        p1 = add_participant(facility["id"], "P1", 6_000_000)
        p2 = add_participant(facility["id"], "P2", 4_000_000)
        commit_participant(p1["id"])
        commit_participant(p2["id"])
        draw = create_draw(facility["id"], 1_000_000)
        # Only P1 funds; P2 stays COMMITTED (never FUNDED).
        wire_and_confirm_due(settlement_for_participant(p1["id"], draw["id"]))

        mod = create_modification(
            facility["id"], borrower["id"], "COVENANT_WAIVER", {"waiver_text": "T"}
        )
        solicit_modification(mod["id"])

        resp = api_client.cast_consent_vote(
            mod["id"], {"vote": "APPROVE"}, make_participant_headers(p2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE, expected_status=409)
        vote = cast_consent_vote(mod["id"], p1["id"], "APPROVE")
        assert vote["status"] == "CAST"


class TestVotingWindowsAndExpiry:
    def test_consent_tally_zero_votes_expires(self):
        """PRD §3.6: "if `cast_share_bps` is below the facility's `quorum_bps` —
        including the case of zero votes — the solicitation moves `SOLICITING` →
        `EXPIRED`".

        Design: Corner/calculations/consent_tally_zero_votes_expires
        """
        setup, mod = _solicited(
            [("EP", 5_000_000)], 1_000_000, "MATURITY_EXTENSION",
            {"new_maturity_date": "2032-08-01"}, total=5_000_000,
        )
        set_clock("2026-08-17T00:00:00Z")
        result = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        assert result["status"] == "EXPIRED"
        assert result["approving_share_bps"] == 0
        assert result["cast_share_bps"] == 0
        assert result["cast_commitment_cents"] == 0

    def test_tally_before_window_close_rejected(self):
        """PRD §3.6: "Attempting it at or before `voting_close_at` fails with
        `ERR_VOTING_STILL_OPEN`."

        Design: Corner/state_machines/tally_before_window_close_rejected
        """
        setup, mod = _solicited(
            [("TP", 5_000_000)], 1_000_000, "COVENANT_WAIVER",
            {"waiver_text": "T"}, total=5_000_000,
        )
        set_clock("2026-08-10T00:00:00Z")  # window closes 2026-08-16
        resp = api_client.tally_close_modification(mod["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_VOTING_STILL_OPEN, expected_status=409)

    def test_vote_after_window_close_rejected(self):
        """PRD §3.6: "A vote may be cast only while the solicitation is
        `SOLICITING` and the clock has not passed `voting_close_at`; otherwise
        `ERR_VOTING_CLOSED`."

        Design: Corner/state_machines/vote_after_window_close_rejected
        """
        setup, mod = _solicited(
            [("LP", 5_000_000)], 1_000_000, "COVENANT_WAIVER",
            {"waiver_text": "T"}, total=5_000_000,
        )
        participant = setup["participants"][0]
        set_clock("2026-08-17T00:00:00Z")
        resp = api_client.cast_consent_vote(
            mod["id"], {"vote": "APPROVE"}, make_participant_headers(participant["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_CLOSED, expected_status=409)

    def test_duplicate_vote_rejected(self):
        """PRD §3.6: "One participant gets one live vote per solicitation: a
        second cast while a `CAST` or `RECAST` vote exists fails with
        `ERR_DUPLICATE_VOTE`, and changing one's mind goes through recasting
        instead."

        Design: Corner/state_machines/duplicate_vote_rejected
        """
        setup, mod = _solicited(
            [("VP", 5_000_000)], 1_000_000, "COVENANT_WAIVER",
            {"waiver_text": "T"}, total=5_000_000,
        )
        participant = setup["participants"][0]
        cast_consent_vote(mod["id"], participant["id"], "APPROVE")
        resp = api_client.cast_consent_vote(
            mod["id"], {"vote": "REJECT"}, make_participant_headers(participant["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE, expected_status=409)


class TestModificationShapeAndImplement:
    def test_modification_terms_incomplete_rejected(self):
        """PRD §3.6: "`terms` must contain exactly the key its type demands —
        `new_interest_rate_bps`, `new_maturity_date`, `commitment_increase_cents`,
        `waiver_text`, `write_down_cents`, or `new_borrower_id` respectively —
        any other combination failing `ERR_INVALID_REQUEST`."

        Design: Corner/validations/modification_terms_incomplete_rejected
        """
        borrower = create_borrower()
        facility = create_facility(borrower["id"], total_commitment_cents=5_000_000)
        resp = api_client.create_modification_request(
            create_modification_payload(facility["id"], "RATE_CHANGE", {}),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_writedown_exceeds_outstanding_rejected(self):
        """PRD §3.6: "A `PRINCIPAL_WRITE_DOWN` requires `write_down_cents` no
        greater than the facility's `outstanding_principal_cents`, failing
        `ERR_WRITEDOWN_EXCEEDS_OUTSTANDING`".
        PRD §3.6: "`PRINCIPAL_WRITE_DOWN` and `BORROWER_SUBSTITUTION` require a
        `UNANIMOUS` consent."

        Design: Corner/validations/writedown_exceeds_outstanding_rejected
        """
        setup, mod = _solicited(
            STANDARD_COMMITMENTS, 5_000_000, "PRINCIPAL_WRITE_DOWN",
            {"write_down_cents": 6_000_000},
        )
        assert mod["required_consent_class"] == "UNANIMOUS"
        assert mod["required_threshold_bps"] == 10_000
        for p in setup["participants"]:
            cast_consent_vote(mod["id"], p["id"], "APPROVE")

        set_clock("2026-08-17T00:00:00Z")
        tally = validate_success(api_client.tally_close_modification(mod["id"], AGENT))
        assert tally["status"] == "PASSED"
        assert tally["approving_share_bps"] == 10_000

        # 6,000,000 write-down exceeds the 5,000,000 outstanding principal.
        resp = api_client.implement_modification(mod["id"], AGENT)
        validate_error(resp, ApiErrorId.ERR_WRITEDOWN_EXCEEDS_OUTSTANDING, expected_status=409)
