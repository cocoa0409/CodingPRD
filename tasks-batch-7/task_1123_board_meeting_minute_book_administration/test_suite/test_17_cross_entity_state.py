"""Cross-entity state dependencies: open_vote requires IN_SESSION; membership
requires the director to be ACTIVE."""
from test_helpers import (
    ApiErrorId,
    add_director,
    add_membership,
    create_meeting_resolution,
    get_success_data,
    open_vote_as_chair,
    schedule_noticed_meeting,
    setup_active_committee,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    table_resolution,
    validate_error,
    make_chair_headers,
    SECRETARY,
)
from test_helpers import api_client


class TestOpenVoteRequiresMeetingInSession:
    """Difficulty instance: open_vote_requires_meeting_in_session."""

    def _setup_tabled_on_noticed_meeting(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp CE1")
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        r = create_meeting_resolution(corp["id"], m["id"], title="R", text="text")
        # Tabling is allowed while the meeting is NOTICED (PRD §3.6).
        table_resolution(r["id"])
        return corp, d1, m, r

    def test_open_vote_on_noticed_meeting_rejected(self, api):
        """PRD §3.6: "Opening requires the resolution to be `TABLED`, the
        linked meeting to be `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`,
        HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/open_vote_requires_meeting_in_session
        """
        _corp, d1, _m, r = self._setup_tabled_on_noticed_meeting(api)
        resp = api.open_vote(r["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_IN_SESSION)
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["status"] == "TABLED"

    def test_open_vote_succeeds_once_meeting_in_session(self, api):
        """PRD §3.6: "Opening requires the resolution to be `TABLED`, the
        linked meeting to be `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`,
        HTTP 422)" — after convening, the same open_vote succeeds.

        Design: Difficulty/cross_entity_state_dependency/open_vote_requires_meeting_in_session
        """
        corp, d1, m, r = self._setup_tabled_on_noticed_meeting(api)
        from test_helpers import record_attendance, set_clock, convene_meeting

        # With 1 ACTIVE director and quorum_fixed_count=1, 1 IN_PERSON satisfies quorum.
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        set_clock("2026-06-20T10:00:00Z")
        convene_meeting(m["id"], d1["id"])
        resp = api.open_vote(r["id"], make_chair_headers(d1["id"]))
        from test_helpers import validate_success

        data = validate_success(resp, expected_status=200)
        assert data["status"] == "VOTE_OPEN"


class TestMembershipRequiresDirectorActive:
    def test_membership_add_fails_for_term_expired_director(self, api):
        """PRD §3.3: "the director must be `ACTIVE` (`ERR_DIRECTOR_NOT_ACTIVE`,
        HTTP 422)" — the gate fires on any non-ACTIVE status, not just
        RESIGNED.

        Design: Difficulty/cross_entity_state_dependency/membership_requires_director_active
        """
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp CE2b")
        d1 = add_director(
            corp["id"], "D1", "d1@x.com",
            term_start="2025-01-01T00:00:00Z", term_end="2026-05-15T00:00:00Z",
        )
        cm = setup_active_committee(corp["id"], name="Nom", committee_type="NOMINATING", quorum_fixed_count=1)
        # Advance clock past D1's term_end and run the checkpoint to expire the term.
        from test_helpers import set_clock

        set_clock("2026-06-01T00:00:00Z")
        api.run_checkpoint(corp["id"], SECRETARY)
        d1_after = get_success_data(api.get_director(d1["id"], SECRETARY))
        assert d1_after["status"] == "TERM_EXPIRED"
        resp = api.create_committee_membership(
            {
                "committee_id": cm["id"],
                "director_id": d1["id"],
                "committee_role": "MEMBER",
                "term_start": "2026-06-01T00:00:00Z",
                "term_end": "2027-06-01T00:00:00Z",
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_DIRECTOR_NOT_ACTIVE)
