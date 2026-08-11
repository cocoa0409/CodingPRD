"""Transitive cascades: meeting-cancel depth-3 chain and director-resignation
depth-2 chain."""
from test_helpers import (
    add_director,
    add_membership,
    cast_ballot,
    create_agenda_item,
    create_meeting_resolution,
    get_success_data,
    open_vote_as_chair,
    set_clock,
    setup_active_committee,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    setup_vote_open_resolution,
    table_resolution,
    validate_success,
    make_director_headers,
    SECRETARY,
)
from test_helpers import api_client


class TestMeetingCancelCascadeToBallots:
    """Difficulty instance: meeting_cancel_cascade_to_ballots.

    Depth-3: Meeting CANCELLED -> AgendaItem DROPPED -> linked Resolution DRAFT
    -> VoteRecords VOIDED.
    """

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp X1")
        d1, d2, d3 = directors
        # Build meeting NOTICED (don't convene yet — resolutions table in NOTICED or IN_SESSION).
        from test_helpers import schedule_noticed_meeting, record_attendance

        m = schedule_noticed_meeting(corp["id"], d1["id"], duration_minutes=120)
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        record_attendance(m["id"], d2["id"], "IN_PERSON")
        record_attendance(m["id"], d3["id"], "IN_PERSON")
        r = create_meeting_resolution(corp["id"], m["id"], title="R cancel", text="text")
        ai = create_agenda_item(m["id"], "Vote on R", 1, d1["id"], resolution_id=r["id"])
        api.include_agenda_item(ai["id"], SECRETARY)
        # Convene, table, open vote, cast one ballot.
        set_clock("2026-06-20T10:00:00Z")
        from test_helpers import convene_meeting

        convene_meeting(m["id"], d1["id"])
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        v1 = cast_ballot(r["id"], d1["id"], "FOR")
        return corp, d1, m, r, ai, v1

    def test_cancel_cascades_meeting_to_agenda(self, api):
        """PRD §3.4: "Every agenda item of the meeting in `PROPOSED` or
        `INCLUDED` drops to `DROPPED`."

        Design: Difficulty/transitive_cascade/meeting_cancel_cascade_to_ballots
        """
        _corp, _d1, m, _r, ai, _v1 = self._setup(api)
        api.cancel_meeting(m["id"], SECRETARY)
        m_after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        ai_after = get_success_data(api.get_agenda_item(ai["id"], SECRETARY))
        assert m_after["status"] == "CANCELLED"
        assert ai_after["status"] == "DROPPED"

    def test_cancel_cascades_to_resolution_and_ballots(self, api):
        """PRD §3.4: "each dropped item that names a `resolution_id` whose
        resolution stands `TABLED` or `VOTE_OPEN` sends that resolution back
        to `DRAFT`, and every `ACTIVE` vote record on such a resolution is
        `VOIDED`."

        Design: Difficulty/transitive_cascade/meeting_cancel_cascade_to_ballots
        """
        _corp, _d1, m, r, _ai, v1 = self._setup(api)
        api.cancel_meeting(m["id"], SECRETARY)
        r_after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        v1_after = get_success_data(api.get_vote_record(v1["id"], SECRETARY))
        assert r_after["status"] == "DRAFT"
        assert r_after["for_count"] == 0
        assert v1_after["status"] == "VOIDED"


class TestDirectorResignationCascade:
    """Difficulty instance: director_resignation_cascade_to_committee_posture."""

    def _setup(self, api):
        corp, _bylaws = setup_corporation_with_adopted_bylaws(name="Corp X2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        d2 = add_director(corp["id"], "D2", "d2@x.com")
        cm = setup_active_committee(corp["id"], name="Comp", committee_type="COMPENSATION", quorum_fixed_count=2)
        mb1 = add_membership(cm["id"], d1["id"], committee_role="CHAIR")
        add_membership(cm["id"], d2["id"], committee_role="MEMBER")
        return corp, d1, d2, cm, mb1

    def test_resignation_ends_memberships_with_director_resigned_reason(self, api):
        """PRD §3.2: "Resignation moves the director `ACTIVE` → `RESIGNED` and
        cascades: every committee membership of that director still `ACTIVE`
        ends with `ended_reason` set to `DIRECTOR_RESIGNED`."

        Design: Difficulty/transitive_cascade/director_resignation_cascade_to_committee_posture
        """
        _corp, d1, _d2, _cm, mb1 = self._setup(api)
        resp = api.resign_director(d1["id"], make_director_headers(d1["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RESIGNED"
        mb_after = get_success_data(api.get_committee_membership(mb1["id"], SECRETARY))
        assert mb_after["status"] == "ENDED"
        assert mb_after["ended_reason"] == "DIRECTOR_RESIGNED"

    def test_resignation_flips_committee_below_quorum_and_chair_vacant(self, api):
        """PRD §3.2: "each affected committee recomputes `chair_vacant` (true
        when no `ACTIVE` membership with `committee_role` `CHAIR` remains)
        and, if its `active_member_count` has fallen below its
        `quorum_fixed_count`, slips from `ACTIVE` to `BELOW_QUORUM`; and the
        corporation's `active_director_count` drops by one."

        Design: Difficulty/transitive_cascade/director_resignation_cascade_to_committee_posture
        """
        corp, d1, _d2, cm, _mb1 = self._setup(api)
        api.resign_director(d1["id"], make_director_headers(d1["id"]))
        cm_after = get_success_data(api.get_committee(cm["id"], SECRETARY))
        assert cm_after["status"] == "BELOW_QUORUM"
        assert cm_after["chair_vacant"] is True
        assert cm_after["active_member_count"] == 1
        corp_after = get_success_data(api.get_corporation(corp["id"], SECRETARY))
        assert corp_after["active_director_count"] == 1
