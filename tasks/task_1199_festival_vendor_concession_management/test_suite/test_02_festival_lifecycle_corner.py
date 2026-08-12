"""Corner: festival lifecycle state machine — successor rule and advance gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_festival,
    api_client,
    create_festival,
    create_festival_payload,
    create_zone,
    decide_application,
    set_clock,
    setup_open_festival,
    setup_reserved_assignment,
    setup_submitted_application,
    start_review,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
OPS = TEST_USERS["ops_headers"]


class TestFestivalSuccessorRule:
    def test_festival_skip_status_rejected(self, api):
        """PRD §3.1: "the advance operation takes a `to_status` that must be the
        immediate successor of the current state; asking for any other target is
        rejected with `ERR_INVALID_STATE_TRANSITION`".

        Design: Corner/state_machines/festival_skip_status_rejected
        """
        festival = create_festival(name="Skip Fest")
        create_zone(festival["id"])
        resp = api.advance_festival_status(festival["id"], {"to_status": "CURATED"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestFestivalOpenGate:
    def test_festival_open_requires_zone(self, api):
        """PRD §3.1: "Opening applications — advancing from `PLANNING` to
        `APPLICATIONS_OPEN` — requires that at least one zone exists for the
        festival; otherwise the advance is rejected with
        `ERR_FESTIVAL_NOT_CONFIGURED`."

        Design: Corner/state_machines/festival_open_requires_zone
        """
        festival = create_festival(name="NoZone Fest")
        resp = api.advance_festival_status(festival["id"], {"to_status": "APPLICATIONS_OPEN"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_CONFIGURED)

        create_zone(festival["id"])
        data = advance_festival(festival["id"], "APPLICATIONS_OPEN")
        assert data["status"] == "APPLICATIONS_OPEN"


class TestFestivalCuratedGate:
    def test_festival_curated_blocked_by_pending_application(self, api):
        """PRD §3.2: "Closing curation — advancing the festival from
        `APPLICATIONS_OPEN` to `CURATED` — requires that no application remain in
        `SUBMITTED`, `UNDER_REVIEW`, or `CHANGES_REQUESTED`; otherwise the advance
        is rejected with `ERR_APPLICATIONS_PENDING_REVIEW`. `WAITLISTED`
        applications may remain."

        Design: Corner/state_machines/festival_curated_blocked_by_pending_application
        """
        scen = setup_submitted_application(name="Pending Fest")
        fest_id = scen["festival"]["id"]
        resp = api.advance_festival_status(fest_id, {"to_status": "CURATED"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATIONS_PENDING_REVIEW)

        start_review(scen["app"]["id"])
        decide_application(scen["app"]["id"], "WAITLISTED")
        data = advance_festival(fest_id, "CURATED")
        assert data["status"] == "CURATED", "WAITLISTED applications may remain at curation close"


class TestFestivalLiveGates:
    def test_festival_live_blocked_by_reserved_assignment(self, api):
        """PRD §3.4: "Advancing the festival from `CURATED` to `LIVE` requires that
        no assignment of the festival remain in `RESERVED` — every reserved
        assignment must have been confirmed or released first, otherwise
        `ERR_ASSIGNMENTS_UNCONFIRMED`".

        Design: Corner/state_machines/festival_live_blocked_by_reserved_assignment
        """
        scen = setup_reserved_assignment(name="Unconf Fest")
        set_clock(scen["festival"]["event_start"])
        resp = api.advance_festival_status(scen["festival"]["id"], {"to_status": "LIVE"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENTS_UNCONFIRMED)

    def test_festival_live_requires_event_start_reached(self, api):
        """PRD §3.4: "and that the logical clock has reached the festival's
        `event_start`; advancing early is rejected with `ERR_FESTIVAL_NOT_STARTED`."

        Design: Corner/state_machines/festival_live_requires_event_start_reached
        """
        festival = create_festival(name="Start Fest")
        create_zone(festival["id"])
        advance_festival(festival["id"], "APPLICATIONS_OPEN")
        advance_festival(festival["id"], "CURATED")

        set_clock("2026-07-10T11:59:59Z")
        resp = api.advance_festival_status(festival["id"], {"to_status": "LIVE"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_STARTED)

        set_clock("2026-07-10T12:00:00Z")
        data = advance_festival(festival["id"], "LIVE")
        assert data["status"] == "LIVE", "at exactly event_start the >= boundary admits LIVE"


class TestFestivalSettlementGate:
    def test_festival_settlement_requires_event_end_passed(self, api):
        """PRD §3.6: "advancing from `LIVE` to `SETTLEMENT` requires the logical
        clock to be strictly past `event_end` (`ERR_FESTIVAL_NOT_ENDED`)".

        Design: Corner/state_machines/festival_settlement_requires_event_end_passed
        """
        festival = create_festival(name="End Fest")
        create_zone(festival["id"])
        advance_festival(festival["id"], "APPLICATIONS_OPEN")
        advance_festival(festival["id"], "CURATED")
        set_clock("2026-07-10T12:00:00Z")
        advance_festival(festival["id"], "LIVE")

        set_clock("2026-07-12T23:00:00Z")  # exactly event_end
        resp = api.advance_festival_status(festival["id"], {"to_status": "SETTLEMENT"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_ENDED)

        set_clock("2026-07-12T23:00:01Z")  # one second past
        data = advance_festival(festival["id"], "SETTLEMENT")
        assert data["status"] == "SETTLEMENT"
