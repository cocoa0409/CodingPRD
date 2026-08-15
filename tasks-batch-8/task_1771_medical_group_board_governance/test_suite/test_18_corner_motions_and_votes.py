"""Corner queue: motion creation mechanics, lifecycle transitions, voting gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    capital_call_payload,
    cast_vote,
    close_motion,
    create_and_open_motion,
    create_merger_proposal,
    create_motion,
    create_motion_payload,
    create_policy,
    create_shareholder,
    create_physician,
    get_motion,
    list_motion_votes,
    list_motions,
    make_physician_headers,
    merger_motion_payload,
    propose_motion,
    set_standing,
    table_motion,
    validate_error,
    withdraw_motion,
)


class TestMotionThresholdTypeComputed:
    def test_threshold_type_from_motion_type_and_client_value_rejected(self, api):
        """PRD §3.4: "A client-supplied `threshold_type` is an unknown field and
        rejected with `ERR_INVALID_REQUEST`: `threshold_type` is always computed from
        the motion type — `SIMPLE_MAJORITY` for `CAPITAL_CALL`, `DISTRIBUTION`, and
        `COMP_POLICY`; `SUPERMAJORITY` for `CHARTER_AMENDMENT`, `BUYOUT_APPROVAL`, and
        `MERGER`."

        Design: Corner/entities/motion_threshold_type_computed_from_motion_type
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        proposal = create_merger_proposal()
        merger_motion = create_motion(
            "MERGER", a, merger_motion_payload(proposal["id"])
        )
        assert merger_motion["threshold_type"] == "SUPERMAJORITY"

        cc_motion = create_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Minor")
        )
        assert cc_motion["threshold_type"] == "SIMPLE_MAJORITY"

        sneaky = create_motion_payload(
            "CAPITAL_CALL", a["id"], capital_call_payload(50000, purpose="Sneaky"),
        )
        sneaky["threshold_type"] = "UNANIMOUS"
        resp = api_client.create_motion(sneaky, make_physician_headers(a["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMotionWithdrawFromOpenRejected:
    def test_withdraw_open_rejected_then_tabled_withdraw_succeeds(self, api):
        """PRD §3.4: "Withdrawal is available from `DRAFT`, `PROPOSED`, or `TABLED`."
        An OPEN motion is outside that set, so the withdrawal is an invalid state
        (`ERR_INVALID_STATE`); after tabling, the same withdrawal succeeds.

        Design: Corner/state_machines/motion_withdraw_from_open_rejected
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Minor")
        )
        resp = api_client.withdraw_motion(motion["id"], make_physician_headers(a["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        table_motion(motion["id"], a)
        withdrawn = withdraw_motion(motion["id"], a)
        assert withdrawn["status"] == "WITHDRAWN"


class TestMotionSupersedeLifecycle:
    def test_supersede_proposed_then_terminal_target_rejected(self, api):
        """PRD §3.4: "A new motion may also name `supersedes_motion_id`; if the target
        motion is `DRAFT` or `PROPOSED` it becomes `SUPERSEDED`, while superseding a
        motion in any later or terminal state is rejected with `ERR_MOTION_TERMINAL`."

        Design: Corner/state_machines/motion_supersede_lifecycle
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        m1 = create_motion("CAPITAL_CALL", a, capital_call_payload(50000, purpose="v1"))
        propose_motion(m1["id"], a)

        m2 = create_motion(
            "CAPITAL_CALL", a, capital_call_payload(60000, purpose="v2"),
            supersedes_motion_id=m1["id"],
        )
        assert m2["status"] == "DRAFT"
        assert get_motion(m1["id"])["status"] == "SUPERSEDED"

        resp = api_client.create_motion(
            create_motion_payload(
                "CAPITAL_CALL", a["id"], capital_call_payload(70000, purpose="v3"),
                supersedes_motion_id=m1["id"],
            ),
            make_physician_headers(a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MOTION_TERMINAL)

        superseding, _meta = list_motions(params={"supersedes_motion_id": m1["id"]})
        assert [m["id"] for m in superseding] == [m2["id"]]


class TestVoteDuplicateAndIneligibleRejections:
    def test_duplicate_snapshot_and_standing_gates(self, api):
        """PRD §3.4: "A ballot is accepted only while the motion is `OPEN`
        (`ERR_MOTION_NOT_OPEN`), only while the clock is strictly before `closes_at`
        (`ERR_VOTING_CLOSED`), only from a physician in the eligible snapshot whose
        standing is still `GOOD_STANDING` at cast time (`ERR_VOTER_INELIGIBLE`), only
        once per physician per motion (`ERR_DUPLICATE_VOTE`)"

        Design: Corner/state_machines/vote_duplicate_and_ineligible_rejections
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        p = create_physician(full_name="Dr P", hire_date="2024-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Minor")
        )
        cast_vote(motion["id"], a, "FOR")
        set_standing(b["id"], "SUSPENDED")

        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "AGAINST"}, make_physician_headers(a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)

        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(p["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_INELIGIBLE)

        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "FOR"}, make_physician_headers(b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_INELIGIBLE)


class TestSimpleMajorityTieRejectsAbstainCountsToQuorum:
    def test_tie_rejects_and_abstain_satisfies_quorum(self, api):
        """PRD §3.4: "For `SIMPLE_MAJORITY`, `required_votes` is an informational 0,
        and the motion is `ADOPTED` when `votes_for` strictly exceeds `votes_against`;
        a tie rejects."
        PRD §3.4: "First quorum: the count of non-voided ballots cast — of any choice,
        including `ABSTAIN` — must be at least `board_quorum_count`, otherwise
        `ERR_QUORUM_NOT_MET`."

        Design: Corner/state_machines/simple_majority_tie_rejects_abstain_counts_to_quorum
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=2)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        create_shareholder("Dr C", 1000, "2017-01-01T00:00:00Z")

        m1 = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Tie case")
        )
        cast_vote(m1["id"], a, "FOR")
        cast_vote(m1["id"], b, "AGAINST")
        closed1 = close_motion(m1["id"])
        assert closed1["status"] == "REJECTED", "a 1-1 tie must reject (strict >)"

        m2 = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Abstain case")
        )
        cast_vote(m2["id"], a, "FOR")
        cast_vote(m2["id"], b, "ABSTAIN")
        closed2 = close_motion(m2["id"])
        assert closed2["status"] == "ADOPTED", (
            "ABSTAIN counts toward the quorum gate (2 ballots >= 2) but not against"
        )
        assert closed2["votes_abstain"] == 1


class TestQuorumCountConfigurableBoundary:
    def test_close_below_configured_quorum_rejected(self, api):
        """PRD §3.4: "First quorum: the count of non-voided ballots cast — of any
        choice, including `ABSTAIN` — must be at least `board_quorum_count`, otherwise
        `ERR_QUORUM_NOT_MET`."
        PRD §2.8 lists `board_quorum_count` (default 5) among the policy constants.

        Design: Corner/calculations/quorum_count_configurable_boundary
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=3)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        c = create_shareholder("Dr C", 1000, "2017-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Quorum test")
        )
        cast_vote(motion["id"], a, "FOR")
        cast_vote(motion["id"], b, "FOR")

        resp = api_client.close_motion(motion["id"], TEST_USERS["board_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)

        cast_vote(motion["id"], c, "ABSTAIN")
        closed = close_motion(motion["id"])
        assert closed["status"] == "ADOPTED"
        assert closed["votes_for"] == 2
        assert closed["votes_abstain"] == 1


class TestVoteInvalidEnumRejected:
    def test_unknown_vote_choice_rejected(self, api):
        """PRD §2.7: "Second, request shape: required fields present, enum values
        valid, amounts positive integers, and the payload sub-fields required by the
        motion type present (`ERR_INVALID_REQUEST`)."
        PRD §3.4: "Ballots are cast by physicians with a `vote_choice` of `FOR`,
        `AGAINST`, or `ABSTAIN`"

        Design: Corner/validations/vote_invalid_enum_rejected
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        motion = create_and_open_motion(
            "CAPITAL_CALL", a, capital_call_payload(50000, purpose="Enum")
        )
        resp = api_client.cast_vote(
            motion["id"], {"vote_choice": "MAYBE"}, make_physician_headers(a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        votes, _meta = list_motion_votes(motion["id"])
        assert votes == []


class TestCapitalCallDueDateInPastRejected:
    def test_backdated_due_date_rejected(self, api):
        """PRD §3.4: "`CAPITAL_CALL` carries `amount_cents`, `due_date`, and
        `purpose`; the due date must be strictly after the clock at motion creation
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/capital_call_due_date_in_past_rejected
        """
        create_policy(total_shares_authorized=1000000)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        resp = api_client.create_motion(
            create_motion_payload(
                "CAPITAL_CALL", a["id"],
                capital_call_payload(50000, due_date="2026-07-01T00:00:00Z",
                                     purpose="Backdated"),
            ),
            make_physician_headers(a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
