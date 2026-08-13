"""Virtual platform sessions and solicitation campaign windows: half-open
overlap semantics, 24-hour same-party buffers, and mode/type gates
(PRD §3.5, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_platform_session, assert_solicitation_campaign,
    create_draft_meeting,
    create_platform_session_payload, create_solicitation_campaign_payload,
)


class TestSessionOverlap:
    """Resource: the meeting's virtual platform. Interval semantics: half-open
    [start_at, end_at)."""

    def test_adjacent_sessions_permitted(self, api, proxy_admin_headers):
        """PRD §3.5: "Sessions of the same meeting may not overlap: a new
        window that overlaps an existing session is rejected with
        `ERR_SESSION_OVERLAP`, though windows that merely touch — one ending
        exactly when the next begins — are permitted."

        Design: Difficulty/resource_temporal_overlap/platform_session_half_open_overlap_adjacency_allowed
        """
        meeting = create_draft_meeting(meeting_mode="VIRTUAL")
        first = api.create_platform_session(
            create_platform_session_payload(
                meeting["id"], session_type="LIVE",
                start_at="2026-09-15T14:00:00Z", end_at="2026-09-15T15:00:00Z",
            ),
            proxy_admin_headers,
        )
        data = validate_success(first, 201)
        assert_platform_session(data)
        adjacent = api.create_platform_session(
            create_platform_session_payload(
                meeting["id"], session_type="REHEARSAL",
                start_at="2026-09-15T13:00:00Z", end_at="2026-09-15T14:00:00Z",
            ),
            proxy_admin_headers,
        )
        adj_data = validate_success(adjacent, 201)
        assert adj_data["status"] == "SCHEDULED", (
            "a window ending exactly when the next begins is permitted (half-open)"
        )

    def test_overlapping_session_rejected(self, api, proxy_admin_headers):
        """PRD §3.5: "Sessions of the same meeting may not overlap: a new
        window that overlaps an existing session is rejected with
        `ERR_SESSION_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/platform_session_half_open_overlap_adjacency_allowed
        """
        meeting = create_draft_meeting(meeting_mode="VIRTUAL")
        validate_success(api.create_platform_session(
            create_platform_session_payload(
                meeting["id"], session_type="LIVE",
                start_at="2026-09-15T14:00:00Z", end_at="2026-09-15T15:00:00Z",
            ),
            proxy_admin_headers,
        ), 201)
        resp = api.create_platform_session(
            create_platform_session_payload(
                meeting["id"], session_type="REHEARSAL",
                start_at="2026-09-15T14:30:00Z", end_at="2026-09-15T15:30:00Z",
            ),
            proxy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP, 409)

    def test_session_on_in_person_meeting_returns_mode_incompatible(self, api, proxy_admin_headers):
        """PRD §3.5: "Booking a session for an `IN_PERSON` meeting makes no
        sense and is rejected with `ERR_MEETING_MODE_INCOMPATIBLE`."

        Design: Corner/validations/session_on_in_person_meeting_returns_mode_incompatible
        """
        meeting = create_draft_meeting(meeting_mode="IN_PERSON")
        resp = api.create_platform_session(
            create_platform_session_payload(meeting["id"]),
            proxy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_MODE_INCOMPATIBLE, 422)


class TestSolicitationCampaigns:
    """Resource: the meeting's shareholder contact list. Same-party windows are
    closed intervals with a mandatory 24-hour buffer."""

    def _contested_meeting(self):
        return create_draft_meeting(meeting_type="CONTESTED")

    def test_same_party_buffer_gap_and_different_party_overlap(self, api, proxy_admin_headers):
        """PRD §3.6: "windows booked by the same `soliciting_party` must be
        separated by at least twenty-four hours: the gap between one window's
        `end_at` and the next window's `start_at` must be twenty-four hours or
        more, in either direction, and a closer pairing is rejected with
        `ERR_CAMPAIGN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/solicitation_campaign_buffer_gap_required
        """
        meeting = self._contested_meeting()
        first = api.create_solicitation_campaign(
            create_solicitation_campaign_payload(meeting["id"]), proxy_admin_headers
        )
        data = validate_success(first, 201)
        assert_solicitation_campaign(data)
        # Same party, 8-hour gap (12:00 -> 20:00): rejected.
        resp = api.create_solicitation_campaign(
            create_solicitation_campaign_payload(
                meeting["id"], start_at="2026-09-01T20:00:00Z", end_at="2026-09-01T21:00:00Z",
            ),
            proxy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP, 409)
        # Different party in that same window: permitted.
        other_party = api.create_solicitation_campaign(
            create_solicitation_campaign_payload(
                meeting["id"], soliciting_party="issuer",
                start_at="2026-09-01T20:00:00Z", end_at="2026-09-01T21:00:00Z",
            ),
            proxy_admin_headers,
        )
        validate_success(other_party, 201)

    def test_same_party_exactly_24h_gap_permitted(self, api, proxy_admin_headers):
        """PRD §3.6: "the gap between one window's `end_at` and the next
        window's `start_at` must be twenty-four hours or more".

        Design: Difficulty/resource_temporal_overlap/solicitation_campaign_buffer_gap_required
        """
        meeting = self._contested_meeting()
        validate_success(api.create_solicitation_campaign(
            create_solicitation_campaign_payload(meeting["id"]), proxy_admin_headers
        ), 201)
        # Exactly 24 hours after the first window's end (09-01 12:00 -> 09-02 12:00).
        resp = api.create_solicitation_campaign(
            create_solicitation_campaign_payload(
                meeting["id"], start_at="2026-09-02T12:00:00Z", end_at="2026-09-02T13:00:00Z",
            ),
            proxy_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_solicitation_campaign(data)

    def test_campaign_window_inverted_returns_invalid_request(self, api, proxy_admin_headers):
        """PRD §3.6: "The window must be well-formed — `end_at` strictly after
        `start_at` — and must close no later than the meeting itself, so an
        `end_at` after `meeting_datetime` is rejected; both shape failures
        surface as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/campaign_window_inverted_returns_invalid_request
        """
        meeting = self._contested_meeting()
        resp = api.create_solicitation_campaign(
            create_solicitation_campaign_payload(
                meeting["id"], start_at="2026-09-01T12:00:00Z", end_at="2026-09-01T09:00:00Z",
            ),
            proxy_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_solicitation_on_non_contested_meeting_returns_not_contested(self, api, proxy_admin_headers):
        """PRD §3.6: "Attempting to book a campaign for a meeting that is not
        `CONTESTED` is rejected with `ERR_MEETING_NOT_CONTESTED`."

        Design: Corner/validations/solicitation_on_non_contested_meeting_returns_not_contested
        """
        meeting = create_draft_meeting(meeting_type="ANNUAL")
        resp = api.create_solicitation_campaign(
            create_solicitation_campaign_payload(meeting["id"]), proxy_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_NOT_CONTESTED, 422)
