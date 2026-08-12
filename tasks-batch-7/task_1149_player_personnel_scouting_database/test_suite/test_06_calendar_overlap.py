"""Temporal resources: prospect calendar (half-open) and facility buffer (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    GM_HEADERS,
    api_client,
    area_headers,
    create_facility_payload,
    create_prospect,
    create_scout,
    create_flag,
    get_success_data,
    schedule_interview,
    validate_error,
)
class TestInterviewHalfOpenAdjacency:
    """Difficulty: resource_temporal_overlap/interview_half_open_adjacency."""

    def _setup(self):
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0)
        p1 = create_prospect(s1, full_name="Busy", position="LB", college="State U")
        iv1 = schedule_interview(
            p1["id"], area_headers(s1),
            start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
            location="Combine",
        )
        return s1, p1, iv1

    def test_adjacent_session_allowed(self, api):
        """PRD §3.8: "half-open semantics mean a new session whose `start_at`
        equals an existing session's `end_at`, or whose `end_at` equals an
        existing session's `start_at`, is allowed".

        Design: Difficulty/resource_temporal_overlap/interview_half_open_adjacency
        """
        s1, p1, _ = self._setup()
        iv2 = schedule_interview(
            p1["id"], area_headers(s1),
            start_at="2026-06-01T11:00:00Z", end_at="2026-06-01T12:00:00Z",
            location="Combine",
        )
        assert iv2["status"] == "SCHEDULED"

    def test_strictly_overlapping_session_rejected(self, api):
        """PRD §3.8: "any stricter overlap is rejected with
        `ERR_INTERVIEW_OVERLAP`". 10:30-11:30 strictly overlaps 10:00-11:00.

        Design: Difficulty/resource_temporal_overlap/interview_half_open_adjacency
        """
        s1, p1, _ = self._setup()
        resp = api_client.schedule_interview(
            p1["id"],
            {"start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:30:00Z",
             "location": "Combine"},
            area_headers(s1),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP)
        assert resp.status_code == 409


class TestFacilityThirtyMinuteBuffer:
    """Difficulty: resource_temporal_overlap/facility_thirty_minute_buffer."""

    def _setup(self):
        resp = api_client.create_facility(
            create_facility_payload(name="Interview Room A", capacity=6), GM_HEADERS
        )
        f1 = get_success_data(resp)
        bk1 = get_success_data(
            api_client.create_booking(
                f1["id"],
                {"start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-01T11:00:00Z",
                 "purpose": "formal interview"},
                GM_HEADERS,
            )
        )
        return f1, bk1

    def test_adjacent_booking_rejected(self, api):
        """PRD §3.8: "Bookings on the same facility must leave a buffer of at
        least 30 minutes on both sides... anything tighter is rejected with
        `ERR_FACILITY_BUFFER_CONFLICT`." A booking starting at 11:00 (gap 0)
        is tighter than 30 minutes.

        Design: Difficulty/resource_temporal_overlap/facility_thirty_minute_buffer
        """
        f1, _ = self._setup()
        resp = api_client.create_booking(
            f1["id"],
            {"start_at": "2026-06-01T11:00:00Z", "end_at": "2026-06-01T12:00:00Z",
             "purpose": "medical"},
            GM_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_BUFFER_CONFLICT)
        assert resp.status_code == 409

    def test_exact_thirty_minute_gap_allowed(self, api):
        """PRD §3.8: "A gap of exactly 30 minutes is permitted". A booking
        starting at 11:30 after one ending at 11:00 leaves exactly 30 minutes.

        Design: Difficulty/resource_temporal_overlap/facility_thirty_minute_buffer
        """
        f1, _ = self._setup()
        bk2 = get_success_data(
            api_client.create_booking(
                f1["id"],
                {"start_at": "2026-06-01T11:30:00Z", "end_at": "2026-06-01T12:30:00Z",
                 "purpose": "medical"},
                GM_HEADERS,
            )
        )
        assert bk2["facility_id"] == f1["id"]


class TestSafetyBeatsTemporalOnInterview:
    """Difficulty: priority_pair_validation_conflict/safety_beats_temporal_on_interview."""

    def _setup(self):
        s1 = create_scout(level="AREA", full_name="S1", weight=1.0)
        p1 = create_prospect(s1, full_name="Flagged", position="CB", college="State U")
        # Book the 10:00-11:00 session BEFORE raising the flag
        schedule_interview(
            p1["id"], area_headers(s1),
            start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T11:00:00Z",
            location="Combine",
        )
        # Move the prospect to UNDER_REVIEW via a CHARACTER flag
        create_flag(
            p1["id"], area_headers(s1),
            flag_type="CHARACTER", severity="LOW", detail="late to meetings",
        )
        return s1, p1

    def test_flag_review_open_reported_not_overlap(self, api):
        """PRD §2.9: "6. Business safety — interview scheduling blocked by
        open flag review, entry add blocked by prospect exclusion
        (`ERR_FLAG_REVIEW_OPEN`, `ERR_PROSPECT_EXCLUDED`). 8. Temporal
        constraints — interview overlap, facility buffer
        (`ERR_INTERVIEW_OVERLAP`, `ERR_FACILITY_BUFFER_CONFLICT`)." The
        10:30-11:30 request both overlaps the existing session AND is blocked
        by the open review; the safety rule (priority 6) fires first and
        reports `ERR_FLAG_REVIEW_OPEN`.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_interview
        """
        s1, p1 = self._setup()
        resp = api_client.schedule_interview(
            p1["id"],
            {"start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:30:00Z",
             "location": "Combine"},
            area_headers(s1),
        )
        data = resp.json()["data"]
        assert data["error_id"] == "ERR_FLAG_REVIEW_OPEN"
        assert data["error_id"] != "ERR_INTERVIEW_OVERLAP"
        assert resp.status_code == 409

    def test_under_review_blocks_even_non_overlapping(self, api):
        """PRD §3.8: "while the prospect's `flag_status` is `UNDER_REVIEW` —
        that is, while any confidential review is open — interview scheduling
        is blocked outright with `ERR_FLAG_REVIEW_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_interview
        """
        s1, p1 = self._setup()
        resp = api_client.schedule_interview(
            p1["id"],
            {"start_at": "2026-06-02T10:00:00Z", "end_at": "2026-06-02T11:00:00Z",
             "location": "Combine"},
            area_headers(s1),
        )
        validate_error(resp, ApiErrorId.ERR_FLAG_REVIEW_OPEN)
