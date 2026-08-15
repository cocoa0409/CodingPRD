"""Board elections: windows, quorum boundary, ballots (PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_ballot_payload,
    create_election_payload,
    get_success_data,
    make_member_headers,
    set_clock,
    setup_cooperative,
    setup_member,
    setup_voting_open_election,
    validate_error,
    validate_success,
)

REP = TEST_USERS["rep"]
SECRETARY = TEST_USERS["board_secretary"]


class TestQuorumBoundary:
    def test_quorum_exactly_at_threshold(self, api):
        """PRD §3.9: "recomputes `quorum_met`: the count of distinct members who
        cast ballots must be at least the ceiling of
        `annual_meeting_quorum_pct` multiplied by the number of `ACTIVE` members
        at the moment of closing."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold
        """
        coop = setup_cooperative()
        set_clock("2026-08-01T00:00:00Z")
        member, _loc = setup_member(status="ACTIVE")
        election = setup_voting_open_election(coop, clock_before_open=False)
        ballot = validate_success(api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=1,
                                  candidate_name="Cand A", is_proxy=False),
            make_member_headers(member["id"])), expected_status=201)
        assert ballot["election_id"] == election["id"]
        set_clock("2026-08-16T00:00:00Z")
        closed = validate_success(api.close_voting(election["id"], SECRETARY), 200)
        # Exactly one ACTIVE member and one distinct ballot:
        # 1 >= ceil(0.05 * 1) = 1 — the >= boundary is met.
        assert closed["quorum_met"] is True

    def test_quorum_below_threshold(self, api):
        """PRD §3.9: "recomputes `quorum_met`: the count of distinct members who
        cast ballots must be at least the ceiling of
        `annual_meeting_quorum_pct` multiplied by the number of `ACTIVE` members
        at the moment of closing."

        Design: Difficulty/boundary_precision_check/quorum_exactly_at_threshold
        """
        coop = setup_cooperative(annual_meeting_quorum_pct=0.5)
        set_clock("2026-08-01T00:00:00Z")
        # Two ACTIVE members -> quorum requires ceil(0.5 * 2) = 1 distinct
        # ballot; zero ballots falls strictly below the boundary.
        m1, _l1 = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "M1", "district_id": 1})
        m2, _l2 = setup_member(
            status="ACTIVE", member_overrides={"legal_name": "M2", "district_id": 2})
        election = setup_voting_open_election(coop, clock_before_open=False)
        set_clock("2026-08-16T00:00:00Z")
        closed = validate_success(api.close_voting(election["id"], SECRETARY), 200)
        assert closed["quorum_met"] is False

    def test_certify_without_quorum_rejected(self, api):
        """PRD §3.9: "Certification (`VOTING_CLOSED → CERTIFIED`) is permitted
        only when quorum was met; without it the attempt fails with
        `ERR_ELECTION_NO_QUORUM`."

        Design: Corner/state_machines/election_certify_without_quorum_rejected
        """
        coop = setup_cooperative()
        set_clock("2026-08-01T00:00:00Z")
        member, _loc = setup_member(status="ACTIVE")
        election = setup_voting_open_election(coop, clock_before_open=False)
        set_clock("2026-08-16T00:00:00Z")
        closed = get_success_data(api.close_voting(election["id"], SECRETARY), 200)
        # Zero ballots cast: 0 < ceil(0.05 * 1) = 1 — quorum not met.
        assert closed["quorum_met"] is False
        resp = api.certify_election(election["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_ELECTION_NO_QUORUM)


class TestElectionWindows:
    def test_open_voting_before_window_rejected(self, api):
        """PRD §3.9: "Opening is also gated on time — the logical clock must
        have reached `voting_opens_at`, else `ERR_ELECTION_WINDOW`"."

        Design: Corner/state_machines/open_voting_before_window_rejected
        """
        coop = setup_cooperative()
        # Clock remains at its 2026-08-01 default, before the September window.
        election = get_success_data(api.create_election(
            create_election_payload(
                cooperative_id=coop["id"],
                voting_opens_at="2026-09-01T00:00:00Z",
                voting_closes_at="2026-09-15T00:00:00Z"),
            SECRETARY), 201)
        get_success_data(api.open_nominations(election["id"], SECRETARY), 200)
        get_success_data(api.close_nominations(
            election["id"], {"candidate_names": ["Cand A"]}, SECRETARY), 200)
        coop_now = get_success_data(api.get_cooperative(coop["id"], SECRETARY), 200)
        resp = api.open_voting(
            election["id"], {"expected_cooperative_version": coop_now["version"]}, SECRETARY)
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW)

    def test_close_nominations_without_candidate_rejected(self, api):
        """PRD §3.9: "Closing nominations takes the declared `candidate_names`
        and requires every contested seat to have at least one declared
        candidate; a seat without a candidate blocks the close with
        `ERR_ELECTION_NO_CANDIDATE`, leaving the election in `NOMINATION_OPEN`."

        Design: Corner/errors/close_nominations_without_candidate_rejected
        """
        coop = setup_cooperative()
        election = get_success_data(api.create_election(
            create_election_payload(cooperative_id=coop["id"]), SECRETARY), 201)
        get_success_data(api.open_nominations(election["id"], SECRETARY), 200)
        resp = api.close_nominations(election["id"], {"candidate_names": []}, SECRETARY)
        validate_error(resp, ApiErrorId.ERR_ELECTION_NO_CANDIDATE)


class TestBallots:
    def _open_election_with_member(self, api, seats=(1,), candidates=("Cand A", "Cand B"),
                                   member_district=1):
        coop = setup_cooperative()
        set_clock("2026-08-05T00:00:00Z")
        member, _loc = setup_member(
            status="ACTIVE", member_overrides={"district_id": member_district})
        election = setup_voting_open_election(
            coop, seats=seats, candidates=candidates, clock_before_open=False)
        return coop, member, election

    def test_ballot_uniqueness_per_member_district(self, api):
        """PRD §3.9: "only one ballot may exist per election, member, and
        district — a repeat cast is rejected with `ERR_BALLOT_ALREADY_CAST`."

        Design: Difficulty/resource_temporal_overlap/ballot_uniqueness_per_member_district
        """
        coop, member, election = self._open_election_with_member(api)
        first = validate_success(api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=1,
                                  candidate_name="Cand A", is_proxy=False),
            make_member_headers(member["id"])), expected_status=201)
        assert first["district"] == 1
        resp = api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=1,
                                  candidate_name="Cand B", is_proxy=False),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BALLOT_ALREADY_CAST)

    def test_ballot_uniqueness_scoped_per_district(self, api):
        """PRD §3.9: "only one ballot may exist per election, member, and
        district — a repeat cast is rejected with `ERR_BALLOT_ALREADY_CAST`";
        the triple includes the district, so the same member voting a second
        contested seat via proxy is a different (election, member, district).

        Design: Difficulty/resource_temporal_overlap/ballot_uniqueness_per_member_district
        """
        coop, member, election = self._open_election_with_member(api, seats=(1, 2))
        validate_success(api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=1,
                                  candidate_name="Cand A", is_proxy=False),
            make_member_headers(member["id"])), expected_status=201)
        second = validate_success(api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=2,
                                  candidate_name="Cand B", is_proxy=True),
            make_member_headers(member["id"])), expected_status=201)
        assert second["district"] == 2
        assert second["is_proxy"] is True

    def test_ballot_district_mismatch_rejected(self, api):
        """PRD §3.9: "a non-proxy ballot's `district` must equal the member's
        own `district_id`, else `ERR_BALLOT_DISTRICT_MISMATCH`, while proxy
        ballots may be cast for any district provided `is_proxy` is true".

        Design: Corner/validations/ballot_district_mismatch_rejected
        """
        coop, member, election = self._open_election_with_member(
            api, seats=(1, 2), member_district=1)
        resp = api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=2,
                                  candidate_name="Cand B", is_proxy=False),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BALLOT_DISTRICT_MISMATCH)

    def test_ballot_from_suspended_member_rejected(self, api):
        """PRD §3.9: "the casting member must be `ACTIVE`, else
        `ERR_BALLOT_MEMBER_INACTIVE`".

        Design: Corner/validations/ballot_from_suspended_member_rejected
        """
        coop, member, election = self._open_election_with_member(api)
        get_success_data(api.suspend_member(member["id"], REP), 200)
        resp = api.cast_ballot(
            create_ballot_payload(election_id=election["id"], district=1,
                                  candidate_name="Cand A", is_proxy=False),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BALLOT_MEMBER_INACTIVE)
