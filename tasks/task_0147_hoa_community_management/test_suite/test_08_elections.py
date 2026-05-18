"""Elections — PRD §3.7.

Covers: candidate nomination window, ballot validations, voting window
boundaries, quorum, certification.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_by_seconds,
    advance_clock_to,
    assert_election_cycle,
    cast_ballot,
    certify_election,
    create_ballot_payload,
    create_candidate_payload,
    create_election_payload,
    create_member,
    create_unit,
    current_clock,
    get_election,
    iso_utc,
    make_member_headers,
    nominate_candidate,
    open_election,
    parse_iso,
    setup_single_unit_roster,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestElectionCreate:

    def test_president_opens_election_returns_nomination(
        self, api, president_role_headers,
    ):
        """PRD §3.7: "The election starts in NOMINATION".

        Claim: POST /hoa/elections returns status=NOMINATION,
        winner_candidate_id=null, eligible_voter_count_at_open=null.
        """
        now = current_clock()
        payload = create_election_payload(
            seat="DIRECTOR",
            nomination_open_at=iso_utc(now),
            voting_open_at=iso_utc(now + timedelta(seconds=60)),
            voting_close_at=iso_utc(now + timedelta(seconds=120)),
        )
        resp = api.create_election(payload, president_role_headers)
        body = validate_success(resp, expected_status=201)
        assert_election_cycle(body)
        assert body["status"] == "NOMINATION"
        assert body["winner_candidate_id"] is None
        assert body["eligible_voter_count_at_open"] is None

    def test_default_quorum_pct_is_0_40(self, api, president_role_headers):
        """PRD §3.7: "The quorum_pct defaults to 0.40 (forty percent)
        when omitted".

        Claim: a created election with no quorum_pct in payload echoes
        quorum_pct == 0.40.
        """
        now = current_clock()
        payload = create_election_payload(
            seat="DIRECTOR",
            nomination_open_at=iso_utc(now),
            voting_open_at=iso_utc(now + timedelta(seconds=60)),
            voting_close_at=iso_utc(now + timedelta(seconds=120)),
            quorum_pct=None,  # omit
        )
        resp = api.create_election(payload, president_role_headers)
        body = validate_success(resp, expected_status=201)
        assert float(body["quorum_pct"]) == 0.40


class TestCandidateNomination:

    def test_nominate_self_in_window_returns_candidate(self, api):
        """PRD §3.7: "any Member may register a Candidate for the
        election by submitting their own member_id (which MUST equal
        X-User-ID). The candidate MUST have eligible_to_vote == true
        at the instant of nomination".

        Claim: a Member who owns a unit (so eligible_to_vote=true) can
        register themselves as a candidate during the nomination window.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=120,
            voting_close_offset_seconds=240,
            quorum_pct=0.10,
        )
        resp = api.create_candidate(
            election["id"],
            create_candidate_payload(member_id=member["id"]),
            make_member_headers(member["id"]),
        )
        body = validate_success(resp, expected_status=201)
        assert body["election_id"] == election["id"]
        assert body["member_id"] == member["id"]

    def test_nominate_at_voting_open_at_returns_nomination_closed(self, api):
        """PRD §3.7: "The nomination instant MUST also lie within the
        half-open interval from nomination_open_at inclusive to
        voting_open_at exclusive; outside that interval the
        registration is rejected with ERR_NOMINATION_CLOSED (HTTP 409)."

        Claim: nominating at exactly voting_open_at falls outside the
        half-open nomination window → ERR_NOMINATION_CLOSED.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=120,
            quorum_pct=0.10,
        )
        # Advance to exactly voting_open_at.
        advance_clock_to(parse_iso(election["voting_open_at"]))
        resp = api.create_candidate(
            election["id"],
            create_candidate_payload(member_id=member["id"]),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOMINATION_CLOSED.value)


class TestBallotWindow:

    def test_ballot_at_voting_open_at_admitted(self, api):
        """PRD §3.7: "The election's status MUST equal VOTING —
        equivalently, the current instant lies in the half-open
        interval from voting_open_at inclusive to voting_close_at
        exclusive".

        Claim: a ballot cast at exactly voting_open_at (inclusive
        boundary) succeeds.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=600,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_open_at"]))
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=member["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_ballot_at_voting_close_at_returns_voting_closed(self, api):
        """PRD §3.7: "a ballot outside that window returns
        ERR_VOTING_CLOSED (HTTP 409)."

        Claim: a ballot cast at exactly voting_close_at falls outside
        the half-open window (exclusive end) → ERR_VOTING_CLOSED.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=120,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_close_at"]))
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=member["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VOTING_CLOSED.value)


class TestBallotDuplicate:

    def test_duplicate_ballot_returns_duplicate_ballot(self, api):
        """PRD §3.7: "The pair (election_id, voter_member_id) MUST be
        unique across all existing Ballot rows; a duplicate is rejected
        with ERR_DUPLICATE_BALLOT (HTTP 409)."

        Claim: a second ballot from the same voter in the same election
        is rejected with ERR_DUPLICATE_BALLOT.
        """
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=600,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_open_at"]))
        # First ballot.
        cast_ballot(election["id"], member["id"], candidate["id"])
        # Second ballot: same (election, voter) → duplicate.
        resp = api.create_ballot(
            election["id"],
            create_ballot_payload(
                voter_member_id=member["id"],
                candidate_id=candidate["id"],
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT.value)
