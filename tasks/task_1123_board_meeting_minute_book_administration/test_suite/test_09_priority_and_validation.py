"""Validation priority pairs and authorization ordering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_director,
    cast_ballot,
    create_corporation,
    create_draft_bylaws,
    file_disclosure,
    get_success_data,
    open_vote_as_chair,
    record_attendance,
    schedule_meeting,
    schedule_noticed_meeting,
    set_clock,
    setup_corporation_with_directors,
    setup_in_session_meeting,
    table_resolution,
    create_meeting_resolution,
    validate_error,
    make_chair_headers,
    make_director_headers,
    SECRETARY,
    AUDITOR,
)
from test_helpers import api_client


class TestConveneCancelledMeetingStateBeatsTemporal:
    """Difficulty instance: convene_cancelled_meeting_state_beats_temporal."""

    def test_convene_cancelled_returns_state_error(self, api):
        """PRD §2.11: "the server evaluates them in a fixed priority order and
        reports the first failure" with tier 5 (State) listed before tier 6
        (Clock-relative temporal rules); a cancelled meeting failing both must
        surface the state error.

        Design: Difficulty/priority_pair_validation_conflict/convene_cancelled_meeting_state_beats_temporal
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp PP1")
        d1 = directors[0]
        m = schedule_meeting(corp["id"], d1["id"])
        api.cancel_meeting(m["id"], SECRETARY)
        # clock still at default 2026-05-01T00:00:00Z, well before start
        resp = api.convene_meeting(m["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["status"] == "CANCELLED"

    def test_convene_noticed_before_start_returns_temporal_error(self, api):
        """PRD §3.4: "the meeting must be `NOTICED`, and the current clock must
        have reached `scheduled_start` — convening early is `ERR_MEETING_NOT_YET`
        (HTTP 422)." A NOTICED meeting (state valid) with clock before start
        fires only the temporal rule, demonstrating that the temporal tier is
        reached only after state passes.

        Design: Difficulty/priority_pair_validation_conflict/convene_cancelled_meeting_state_beats_temporal
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp PP1b")
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        # clock still 2026-05-01, before 2026-06-20 start
        resp = api.convene_meeting(m["id"], make_chair_headers(d1["id"]))
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_YET)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["status"] == "NOTICED"


class TestConflictedSecondBallotSafetyBeatsDuplicate:
    """Difficulty instance: conflicted_director_second_ballot_safety_beats_duplicate.

    D3 has OPEN disclosure for 'Acme' and already cast RECUSED. A second cast
    that is non-RECUSED violates both the recusal-compliance rule (priority 7)
    and one-ballot-per uniqueness (priority 8); the safety error wins.
    """

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(3, name="Corp PP2")
        d1, d2, d3 = directors
        file_disclosure(d3["id"], corp["id"], related_party="Acme")
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        record_attendance(m["id"], d1["id"], "IN_PERSON")
        record_attendance(m["id"], d2["id"], "IN_PERSON")
        record_attendance(m["id"], d3["id"], "IN_PERSON")
        set_clock("2026-06-20T10:00:00Z")
        from test_helpers import convene_meeting

        convene_meeting(m["id"], d1["id"])
        r = create_meeting_resolution(
            corp["id"], m["id"], title="Acme deal", text="text", related_party="Acme"
        )
        table_resolution(r["id"])
        open_vote_as_chair(r["id"], d1["id"])
        cast_ballot(r["id"], d3["id"], "RECUSED")
        return corp, d1, d3, m, r

    def test_conflicted_second_non_recused_ballot_returns_recusal_error(self, api):
        """PRD §2.11: "A request failing an earlier tier never reaches a later
        one: ... a duplicate ballot surfaces only after the context, role,
        schema, existence, state, temporal, and compliance tiers have all
        passed." Compliance (tier 7) precedes uniqueness (tier 8).

        Design: Difficulty/priority_pair_validation_conflict/conflicted_director_second_ballot_safety_beats_duplicate
        """
        _corp, _d1, d3, _m, r = self._setup(api)
        resp = api.create_vote_record(
            {"resolution_id": r["id"], "channel": "MEETING_BALLOT", "vote": "FOR"},
            make_director_headers(d3["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONFLICT_RECUSAL_REQUIRED)

    def test_tallies_reflect_only_first_compliant_recusal(self, api):
        """PRD §3.6: "Four tallies live on the resolution — `for_count`,
        `against_count`, `abstain_count`, and `recused_count` — all zero while
        the resolution is a draft, thereafter counting its `ACTIVE` vote records
        of each value and recomputed on every cast, recast, and voiding."

        Design: Difficulty/priority_pair_validation_conflict/conflicted_director_second_ballot_safety_beats_duplicate
        """
        _corp, _d1, d3, _m, r = self._setup(api)
        api.create_vote_record(
            {"resolution_id": r["id"], "channel": "MEETING_BALLOT", "vote": "FOR"},
            make_director_headers(d3["id"]),
        )
        after = get_success_data(api.get_resolution(r["id"], SECRETARY))
        assert after["recused_count"] == 1
        assert after["for_count"] == 0


class TestAuthorizationBeatsNotFound:
    def test_forbidden_role_beats_not_found(self, api):
        """PRD §2.11: "A request failing an earlier tier never reaches a later
        one." Authorization (tier 2) precedes existence (tier 4).

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        resp = api.table_resolution(NON_EXISTENT_UUID, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403


class TestMissingAuthHeader:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for one, is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api._request("GET", "/directors", headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_CONTEXT_HEADER)
        assert resp.status_code == 400
