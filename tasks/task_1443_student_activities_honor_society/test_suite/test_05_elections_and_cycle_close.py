"""Officer elections: open idempotency, the empty-ballot boundary, tally
counting and ties, and the cycle-close dependency on election state."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_election,
    cast_vote,
    create_election_payload,
    setup_cycle_in_review,
    setup_cycle_inducted_all_rejected,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]


def _open_election(env, office="PRESIDENT"):
    resp = api_client.create_election(
        env["chapter"]["id"],
        create_election_payload(env["cycle"]["id"], office), ADVISOR)
    election = validate_success(resp, expected_status=201)
    election = validate_success(
        api_client.open_election(env["chapter"]["id"], election["id"], ADVISOR))
    assert election["status"] == "OPEN"
    return election


class TestElectionOpenGuards:
    def test_double_open_rejected(self):
        """PRD section 3.4: "Opening an election moves it from `DRAFT` to
        `OPEN` and is guarded by three checks in order."
        PRD section 2.6: "then the target resource's state-machine legality
        (`ERR_INVALID_STATE`, HTTP 409, raised whenever a transition is
        attempted from a state that does not permit it)."

        Design: Corner/state_machines/election_idempotency_double_open_rejected
        """
        env = setup_cycle_in_review()
        election = _open_election(env)
        resp = api_client.open_election(env["chapter"]["id"], election["id"],
                                        ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestElectionTallyEmptySet:
    def test_tally_with_no_votes_rejected(self):
        """PRD section 3.4: "Tallying moves the election from `OPEN` to
        `TALLIED` and requires at least one vote in `CAST`; tallying an empty
        ballot box is rejected with `ERR_NO_VOTES_CAST` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/election_tally_no_votes_empty_set
        """
        env = setup_cycle_in_review()
        election = _open_election(env, office="HISTORIAN")
        resp = api_client.tally_election(env["chapter"]["id"], election["id"],
                                         ADVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_VOTES_CAST)
        after = validate_success(
            api_client.get_election(env["chapter"]["id"], election["id"],
                                    ADVISOR))
        assert after["status"] == "OPEN"

    def test_tally_with_single_vote_names_winner(self):
        """PRD section 3.4: "If a single candidate holds the highest count,
        that member's `id` becomes `winner_member_id` and `runoff_required` is
        set to false."
        PRD section 3.4: "Tallying stamps `tallied_at`."

        Design: Difficulty/boundary_precision_check/election_tally_no_votes_empty_set
        """
        env = setup_cycle_in_review()
        member = env["members"][0]
        election = _open_election(env, office="HISTORIAN")
        cast_vote(env["chapter"]["id"], election["id"], member["id"],
                  member["id"])
        resp = api_client.tally_election(env["chapter"]["id"], election["id"],
                                         ADVISOR)
        data = validate_success(resp)
        assert_election(data)
        assert data["status"] == "TALLIED"
        assert data["winner_member_id"] == member["id"]
        assert data["runoff_required"] is False
        assert data["tallied_at"]


class TestElectionTallyCounting:
    def test_tally_counts_votes_and_names_top_candidate(self):
        """PRD section 3.4: "The tally counts the `CAST` votes per candidate.
        If a single candidate holds the highest count, that member's `id`
        becomes `winner_member_id` and `runoff_required` is set to false."

        Design: Corner/calculations/election_tally_correct_counting
        """
        env = setup_cycle_in_review(member_overrides=[{} for _ in range(6)])
        a, b, c, v1, v2, v3 = [m["id"] for m in env["members"]]
        election = _open_election(env)
        ch_id, el_id = env["chapter"]["id"], election["id"]
        for voter, candidate in ((a, a), (b, a), (c, a),
                                 (v1, b), (v2, b), (v3, c)):
            cast_vote(ch_id, el_id, voter, candidate)
        resp = api_client.tally_election(ch_id, el_id, ADVISOR)
        data = validate_success(resp)
        assert data["status"] == "TALLIED"
        # Vote counts: A=3, B=2, C=1 — a single top candidate.
        assert data["winner_member_id"] == a
        assert data["runoff_required"] is False

    def test_tie_at_the_top_triggers_runoff(self):
        """PRD section 3.4: "If two or more candidates share the top count,
        `winner_member_id` is null and `runoff_required` is true — a tie is a
        tie, and vote timestamps are never consulted to break one."

        Design: Corner/calculations/election_tally_tie_triggers_runoff
        """
        env = setup_cycle_in_review(member_overrides=[{} for _ in range(4)])
        a, b, v1, v2 = [m["id"] for m in env["members"]]
        election = _open_election(env)
        ch_id, el_id = env["chapter"]["id"], election["id"]
        for voter, candidate in ((a, a), (b, b), (v1, a), (v2, b)):
            cast_vote(ch_id, el_id, voter, candidate)
        resp = api_client.tally_election(ch_id, el_id, ADVISOR)
        data = validate_success(resp)
        assert data["status"] == "TALLIED"
        assert data["winner_member_id"] is None
        assert data["runoff_required"] is True


class TestCycleCloseElectionDependency:
    def test_close_blocked_while_election_uncertified(self):
        """PRD section 3.2: "A cycle closes from `INDUCTED` once every officer
        election tied to its `cycle_id` has reached `CERTIFIED` or `VOIDED` —
        and, independently, the cycle must have produced at least one
        `INDUCTED` application before it may close, else the close is rejected
        with `ERR_NO_INDUCTED_APPLICATIONS` (HTTP 409); the election check is
        evaluated first, as a state-legality matter, and the
        inducted-application check second."
        PRD section 2.6: "then the target resource's state-machine legality
        (`ERR_INVALID_STATE`, HTTP 409, raised whenever a transition is
        attempted from a state that does not permit it)."

        Design: Difficulty/cross_entity_state_dependency/cycle_close_blocked_by_uncertified_election
        """
        env = setup_cycle_inducted_all_rejected()
        ch_id, cy_id = env["chapter"]["id"], env["cycle"]["id"]
        resp = api_client.create_election(
            ch_id, create_election_payload(cy_id, "PRESIDENT"), ADVISOR)
        validate_success(resp, expected_status=201)
        # The DRAFT election is neither CERTIFIED nor VOIDED.
        resp = api_client.close_cycle(ch_id, cy_id, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cycle_after = validate_success(api_client.get_cycle(ch_id, cy_id,
                                                            ADVISOR))
        assert cycle_after["status"] == "INDUCTED"

    def test_close_with_elections_resolved_but_no_inducted_applications(self):
        """PRD section 3.2: "the cycle must have produced at least one
        `INDUCTED` application before it may close, else the close is rejected
        with `ERR_NO_INDUCTED_APPLICATIONS` (HTTP 409); the election check is
        evaluated first, as a state-legality matter, and the
        inducted-application check second."

        Design: Difficulty/cross_entity_state_dependency/cycle_close_blocked_by_uncertified_election
        """
        env = setup_cycle_inducted_all_rejected()
        ch_id, cy_id = env["chapter"]["id"], env["cycle"]["id"]
        resp = api_client.create_election(
            ch_id, create_election_payload(cy_id, "PRESIDENT"), ADVISOR)
        election = validate_success(resp, expected_status=201)
        # Void the DRAFT election so the election check passes; the all-
        # REJECTED pool means no INDUCTED application exists.
        validate_success(api_client.void_election(ch_id, election["id"],
                                                  ADVISOR))
        resp = api_client.close_cycle(ch_id, cy_id, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_INDUCTED_APPLICATIONS)
