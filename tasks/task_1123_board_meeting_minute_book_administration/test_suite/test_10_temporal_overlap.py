"""Resource temporal overlap: meeting calendar half-open semantics vs
disclosure closed-interval semantics, and other temporal boundaries."""
from test_helpers import (
    ApiErrorId,
    add_director,
    add_document,
    create_corporation,
    create_package,
    file_disclosure,
    get_success_data,
    schedule_meeting,
    schedule_noticed_meeting,
    set_clock,
    setup_corporation_with_adopted_bylaws,
    setup_corporation_with_directors,
    validate_error,
    validate_success,
    make_director_headers,
    SECRETARY,
)
from test_helpers import api_client


class TestMeetingCalendarHalfOpenAdjacency:
    """Difficulty instance: meeting_calendar_half_open_adjacency_allowed."""

    def _setup(self, api):
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp T1")
        d1 = directors[0]
        m_a = schedule_meeting(
            corp["id"], d1["id"], scheduled_start="2026-06-20T10:00:00Z", duration_minutes=60
        )
        return corp, d1, m_a

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §2.8: "Meeting calendar windows and director or membership terms
        are half-open: the start instant is included, the end instant is
        excluded, so two meetings scheduled back to back — one ending exactly
        when the next begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/meeting_calendar_half_open_adjacency_allowed
        """
        corp, d1, _m_a = self._setup(api)
        resp = api.create_meeting(
            {
                "corporation_id": corp["id"],
                "meeting_type": "SPECIAL",
                "scheduled_start": "2026-06-20T11:00:00Z",
                "duration_minutes": 60,
                "location_or_medium": "Boardroom",
                "chair_director_id": d1["id"],
            },
            SECRETARY,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_interior_overlap_rejected(self, api):
        """PRD §3.4: "If any other meeting of the same corporation that is not
        `CANCELLED` holds a window starting strictly before the new window's
        end and ending strictly after the new window's start, the schedule is
        refused with `ERR_MEETING_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/meeting_calendar_half_open_adjacency_allowed
        """
        corp, d1, _m_a = self._setup(api)
        resp = api.create_meeting(
            {
                "corporation_id": corp["id"],
                "meeting_type": "SPECIAL",
                "scheduled_start": "2026-06-20T10:30:00Z",
                "duration_minutes": 60,
                "location_or_medium": "Boardroom",
                "chair_director_id": d1["id"],
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_TIME_CONFLICT)


class TestDisclosureWindowClosedInterval:
    """Difficulty instance: disclosure_window_closed_interval_touching_conflicts."""

    def test_touching_endpoints_conflict_under_closed_semantics(self, api):
        """PRD §2.8: "Conflict disclosure windows are closed intervals with
        both ends inclusive, so a new disclosure that merely touches an
        existing one at an endpoint does conflict." PRD §3.8: "because the
        windows are closed intervals, a filing whose start falls on the exact
        day an existing window ends is already a conflict, rejected with
        `ERR_DISCLOSURE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/disclosure_window_closed_interval_touching_conflicts
        """
        corp = create_corporation(name="Corp T2")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        # Existing OPEN window [2026-01-01, 2026-06-30]
        resp = api.create_conflict_disclosure(
            {
                "director_id": d1["id"],
                "corporation_id": corp["id"],
                "related_party": "Acme",
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2026-06-30T00:00:00Z",
            },
            make_director_headers(d1["id"]),
        )
        get_success_data(resp)
        # Touching window starting at existing window's end
        resp2 = api.create_conflict_disclosure(
            {
                "director_id": d1["id"],
                "corporation_id": corp["id"],
                "related_party": "Acme",
                "effective_from": "2026-06-30T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
            make_director_headers(d1["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_DISCLOSURE_WINDOW_CONFLICT)

    def test_strictly_after_existing_window_accepted(self, api):
        """PRD §3.8: "Two disclosures of the same director for the same
        `related_party` may not overlap while both are `OPEN`" — a window
        strictly after the existing one does not overlap and is accepted.

        Design: Difficulty/resource_temporal_overlap/disclosure_window_closed_interval_touching_conflicts
        """
        corp = create_corporation(name="Corp T2b")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        api.create_conflict_disclosure(
            {
                "director_id": d1["id"],
                "corporation_id": corp["id"],
                "related_party": "Acme",
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_to": "2026-06-30T00:00:00Z",
            },
            make_director_headers(d1["id"]),
        )
        resp = api.create_conflict_disclosure(
            {
                "director_id": d1["id"],
                "corporation_id": corp["id"],
                "related_party": "Acme",
                "effective_from": "2026-07-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
            make_director_headers(d1["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "OPEN"


class TestScheduleMeetingInPast:
    def test_schedule_meeting_in_past_rejected(self, api):
        """PRD §3.4: "The start must lie strictly after the current clock — a
        past or exactly-current start is `ERR_SCHEDULED_START_IN_PAST`
        (HTTP 422)."

        Design: Corner/errors/schedule_meeting_in_past_rejected
        """
        corp = create_corporation(name="Corp R6")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        set_clock("2026-06-01T00:00:00Z")
        resp = api.create_meeting(
            {
                "corporation_id": corp["id"],
                "meeting_type": "REGULAR",
                "scheduled_start": "2026-06-01T00:00:00Z",
                "duration_minutes": 60,
                "location_or_medium": "Boardroom",
                "chair_director_id": d1["id"],
            },
            SECRETARY,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULED_START_IN_PAST)


class TestDistributeAfterLeadWindow:
    def test_distribute_after_lead_window_rejected(self, api):
        """PRD §3.5: "a distribution attempted past that boundary is
        `ERR_PACKAGE_DISTRIBUTION_LATE` (HTTP 422)."

        Design: Corner/errors/distribute_after_lead_window_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp R7")
        d1 = directors[0]
        m = schedule_noticed_meeting(corp["id"], d1["id"])
        p = create_package(m["id"])
        add_document(p["id"], "Agenda", "s3://a", "GENERAL")
        api.seal_board_package(p["id"], SECRETARY)
        # package_lead_days=5 -> deadline 2026-06-15T10:00Z; clock 1s past.
        set_clock("2026-06-15T10:00:01Z")
        resp = api.distribute_board_package(p["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_DISTRIBUTION_LATE)
        after = get_success_data(api.get_board_package(p["id"], SECRETARY))
        assert after["status"] == "SEALED"


class TestSealEmptyPackage:
    def test_seal_empty_package_rejected(self, api):
        """PRD §3.5: "it requires the package to be `ASSEMBLING`, to hold at
        least one document (`ERR_PACKAGE_EMPTY`, HTTP 422)".

        Design: Corner/errors/seal_empty_package_rejected
        """
        corp = create_corporation(name="Corp R8")
        d1 = add_director(corp["id"], "D1", "d1@x.com")
        m = schedule_meeting(corp["id"], d1["id"])
        p = create_package(m["id"])
        resp = api.seal_board_package(p["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_EMPTY)
        after = get_success_data(api.get_board_package(p["id"], SECRETARY))
        assert after["status"] == "ASSEMBLING"


class TestIncludeAgendaAfterConvene:
    def test_include_agenda_after_convene_rejected(self, api):
        """PRD §3.5: "once the meeting has advanced past notice, the agenda is
        locked and inclusion fails with `ERR_AGENDA_LOCKED` (HTTP 422)."

        Design: Corner/errors/include_agenda_after_convene_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp R9")
        d1 = directors[0]
        m = schedule_meeting(corp["id"], d1["id"])
        ai_resp = api.create_agenda_item(
            {
                "meeting_id": m["id"],
                "title": "Late item",
                "order_index": 1,
                "proposed_by_director_id": d1["id"],
            },
            SECRETARY,
        )
        ai = get_success_data(ai_resp)
        api.send_notices(m["id"], SECRETARY)
        set_clock("2026-06-20T10:00:00Z")
        from test_helpers import convene_meeting

        convene_meeting(m["id"], d1["id"])
        resp = api.include_agenda_item(ai["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_AGENDA_LOCKED)
        after = get_success_data(api.get_agenda_item(ai["id"], SECRETARY))
        assert after["status"] == "PROPOSED"


class TestSendNoticesWithoutDirectors:
    def test_send_notices_without_active_directors_rejected(self, api):
        """PRD §3.4: "Sending notices — a secretary act on a `SCHEDULED`
        meeting — requires an adopted bylaws (`ERR_NO_ADOPTED_BYLAWS`) and at
        least one `ACTIVE` director (`ERR_NO_ACTIVE_DIRECTORS`, HTTP 422)."

        Design: Corner/errors/send_notices_without_directors_rejected
        """
        corp, _bylaws, directors = setup_corporation_with_directors(1, name="Corp RA")
        d1 = directors[0]
        m = schedule_meeting(corp["id"], d1["id"])
        api.resign_director(d1["id"], SECRETARY)
        resp = api.send_notices(m["id"], SECRETARY)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_DIRECTORS)
        after = get_success_data(api.get_meeting(m["id"], SECRETARY))
        assert after["status"] == "SCHEDULED"
