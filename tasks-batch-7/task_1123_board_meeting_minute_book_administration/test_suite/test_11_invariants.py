"""Compensating invariants: recast conserves ACTIVE ballot count; membership
add+end conserves committee size. Plus the immediate-consistency check."""
from test_helpers import (
    add_director,
    add_membership,
    cast_ballot,
    create_meeting_resolution,
    get_success_data,
    open_vote_as_chair,
    setup_active_committee,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    table_resolution,
    validate_paginated,
    validate_success,
    make_director_headers,
    SECRETARY,
    AUDITOR,
)
from test_helpers import api_client


class TestRecastConservesActiveBallotCount:
    """Difficulty instance: vote_recast_conserves_active_ballot_count."""

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp I1")
        d1, d2, d3 = directors
        m = setup_in_session_meeting(corp["id"], d1["id"], [d["id"] for d in directors])
        r = create_meeting_resolution(corp["id"], m["id"], title="R inv", text="text")
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        cast_ballot(r["id"], d1["id"], "FOR")
        cast_ballot(r["id"], d2["id"], "AGAINST")
        v3 = cast_ballot(r["id"], d3["id"], "FOR")
        return corp, d1, d3, m, r, v3

    def test_recast_changes_distribution_not_count(self, api):
        """PRD §3.6: "recasting replaces the `vote` on their own `ACTIVE`
        ballot, increments `recast_count`, recomputes the resolution's
        tallies, and leaves the count of `ACTIVE` ballots unchanged."

        Design: Difficulty/compensating_invariant/vote_recast_conserves_active_ballot_count
        """
        _corp, _d1, d3, _m, r, v3 = self._setup(api)
        resp = api.recast_vote(v3["id"], {"vote": "AGAINST"}, make_director_headers(d3["id"]))
        validate_success(resp, expected_status=200)
        # Count of ACTIVE VoteRecords for this resolution stays at 3.
        list_resp = api.list_vote_records(
            SECRETARY, params={"resolution_id": r["id"], "status": "ACTIVE"}
        )
        _rows, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 3, (
            f"ACTIVE ballot count must be conserved at 3, got {meta['total_count']}"
        )
        # Distribution moved: for 2 -> 1, against 1 -> 2.
        r_after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert r_after["for_count"] == 1
        assert r_after["against_count"] == 2

    def test_recast_increments_recast_count_on_ballot(self, api):
        """PRD §3.6: "recasting replaces the `vote` on their own `ACTIVE`
        ballot, increments `recast_count`."

        Design: Difficulty/compensating_invariant/vote_recast_conserves_active_ballot_count
        """
        _corp, _d1, d3, _m, _r, v3 = self._setup(api)
        resp = api.recast_vote(v3["id"], {"vote": "AGAINST"}, make_director_headers(d3["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ACTIVE"
        assert data["recast_count"] == 1
        assert data["vote"] == "AGAINST"


class TestMembershipAddEndConservesCommitteeSize:
    """Difficulty instance: membership_add_end_conserves_committee_size."""

    def _setup(self, api):
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp I2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        d2 = add_director(corp["id"], "D2", "d2@x.com")
        cm = setup_active_committee(corp["id"], name="Nom", committee_type="NOMINATING", quorum_fixed_count=1)
        add_membership(cm["id"], d1["id"], committee_role="CHAIR")
        return corp, d1, d2, cm

    def test_add_then_end_returns_committee_to_prior_size(self, api):
        """PRD §3.3: "On a successful add the committee's `active_member_count`
        rises by one ... Ending a membership ... the committee's
        `active_member_count` falls by one."

        Design: Difficulty/compensating_invariant/membership_add_end_conserves_committee_size
        """
        _corp, _d1, d2, cm = self._setup(api)
        mb2 = add_membership(cm["id"], d2["id"], committee_role="MEMBER", term_end="2027-02-01T00:00:00Z")
        api.end_committee_membership(mb2["id"], SECRETARY)
        after = get_success_data(api.get_committee(cm["id"], SECRETARY))
        assert after["active_member_count"] == 1, (
            f"expected conservation at 1, got {after['active_member_count']}"
        )
        assert after["status"] == "ACTIVE"
        assert after["chair_vacant"] is False

    def test_ended_membership_records_manual_reason(self, api):
        """PRD §3.3: "Ending a membership is normally a manual secretary act:
        the membership moves `ACTIVE` → `ENDED` with `ended_reason` `MANUAL`."

        Design: Difficulty/compensating_invariant/membership_add_end_conserves_committee_size
        """
        _corp, _d1, d2, cm = self._setup(api)
        mb2 = add_membership(cm["id"], d2["id"], committee_role="MEMBER", term_end="2027-02-01T00:00:00Z")
        api.end_committee_membership(mb2["id"], SECRETARY)
        mb_after = get_success_data(api.get_committee_membership(mb2["id"], SECRETARY))
        assert mb_after["status"] == "ENDED"
        assert mb_after["ended_reason"] == "MANUAL"


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD §2.10: "the server performs those reconciliations as part of
        the same operation rather than leaving them to clients."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp IC1")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        cm = setup_active_committee(corp["id"], name="C", committee_type="SPECIAL", quorum_fixed_count=1)
        add_membership(cm["id"], d1["id"], committee_role="CHAIR")
        after = get_success_data(api.get_committee(cm["id"], AUDITOR))
        assert after["active_member_count"] == 1
        assert after["chair_vacant"] is False
