"""NDA-gated data room and management-meeting scheduling: buffer, interval, and precedence rules."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_broker_headers, make_buyer_headers,
    create_meeting_payload,
)
from test_helpers import fixtures as fx


def _active_listing_with_nda_buyer(api, sign_second_buyer_nda=False):
    """Active listing + Buyer-A (NDA signed) + Buyer-B (NDA optional). Returns dict."""
    s = fx.setup_active_listing(api)
    hdr = make_broker_headers(s["broker"]["id"])
    buyer_a = fx.onboard_buyer(api, full_name="Buyer A", email="a@x.com")
    buyer_b = fx.onboard_buyer(api, full_name="Buyer B", email="b@x.com")
    fx.sign_nda(api, buyer_a["id"], s["listing"]["id"])
    if sign_second_buyer_nda:
        fx.sign_nda(api, buyer_b["id"], s["listing"]["id"])
    s.update({"hdr": hdr, "buyer_a": buyer_a, "buyer_b": buyer_b})
    return s


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_meeting_schedule
# ---------------------------------------------------------------------------
class TestReferentialBeatsTemporalOnMeeting:
    def _setup(self, api):
        s = _active_listing_with_nda_buyer(api)
        # Buyer-A (NDA) holds 10:00-11:00.
        validate_success(
            api.schedule_meeting(
                s["listing"]["id"],
                create_meeting_payload(s["buyer_a"]["id"], "2026-03-01T10:00:00Z", "2026-03-01T11:00:00Z"),
                s["hdr"],
            ),
            expected_status=201,
        )
        return s

    def test_missing_nda_reported_over_slot_conflict(self, api):
        """PRD §3.3: "Scheduling requires that the named buyer hold a `SIGNED` NDA on the listing,
        again enforced with `ERR_NDA_REQUIRED`."
        PRD §2.6: "When several checks could reject the same request, they are evaluated in a
        fixed priority order so that the returned error is deterministic."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_meeting_schedule
        """
        s = self._setup(api)
        # Buyer-B has NO NDA and overlaps the buffer (10:30-11:30).
        resp = api.schedule_meeting(
            s["listing"]["id"],
            create_meeting_payload(s["buyer_b"]["id"], "2026-03-01T10:30:00Z", "2026-03-01T11:30:00Z"),
            s["hdr"],
        )
        validate_error(resp, ApiErrorId.ERR_NDA_REQUIRED.value)

    def test_rejected_conflicting_meeting_not_persisted(self, api):
        """PRD §3.3: "Scheduling requires that the named buyer hold a `SIGNED` NDA on the listing,
        again enforced with `ERR_NDA_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_meeting_schedule
        """
        s = self._setup(api)
        api.schedule_meeting(
            s["listing"]["id"],
            create_meeting_payload(s["buyer_b"]["id"], "2026-03-01T10:30:00Z", "2026-03-01T11:30:00Z"),
            s["hdr"],
        )
        data, _meta = _list(api, s)
        assert len(data) == 1, "only Buyer-A's meeting should persist"


def _list(api, s):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_listing_meetings(s["listing"]["id"], s["hdr"]))


# ---------------------------------------------------------------------------
# Design: Difficulty/resource_temporal_overlap/meeting_within_buffer_conflict
# ---------------------------------------------------------------------------
class TestMeetingBufferSeparation:
    def _setup_with_first_meeting(self, api):
        s = _active_listing_with_nda_buyer(api)
        validate_success(
            api.schedule_meeting(
                s["listing"]["id"],
                create_meeting_payload(s["buyer_a"]["id"], "2026-03-01T10:00:00Z", "2026-03-01T11:00:00Z"),
                s["hdr"],
            ),
            expected_status=201,
        )
        return s

    def test_gap_under_thirty_minutes_rejected(self, api):
        """PRD §3.3: "a new scheduled meeting is rejected with `ERR_MEETING_SLOT_CONFLICT` when the
        gap between it and any existing scheduled meeting on the same listing is strictly less
        than thirty minutes."

        Design: Difficulty/resource_temporal_overlap/meeting_within_buffer_conflict
        """
        s = self._setup_with_first_meeting(api)
        # 11:00 end -> 11:15 start = 15-minute gap, strictly less than 30.
        resp = api.schedule_meeting(
            s["listing"]["id"],
            create_meeting_payload(s["buyer_a"]["id"], "2026-03-01T11:15:00Z", "2026-03-01T12:00:00Z"),
            s["hdr"],
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_SLOT_CONFLICT.value)

    def test_gap_exactly_thirty_minutes_allowed(self, api):
        """PRD §3.3: "A gap of exactly thirty minutes is permitted — the buffer boundary is
        inclusive of the thirty-minute separation and exclusive only of gaps narrower than it."

        Design: Difficulty/resource_temporal_overlap/meeting_within_buffer_conflict
        """
        s = self._setup_with_first_meeting(api)
        # 11:00 end -> 11:30 start = exactly 30-minute gap.
        data = validate_success(
            api.schedule_meeting(
                s["listing"]["id"],
                create_meeting_payload(s["buyer_a"]["id"], "2026-03-01T11:30:00Z", "2026-03-01T12:30:00Z"),
                s["hdr"],
            ),
            expected_status=201,
        )
        assert data["status"] == "SCHEDULED"


def test_meeting_end_not_after_start_rejected(api):
    """PRD §3.3: "The `end_at` must be strictly after the `start_at`, or the request fails with
    `ERR_INVALID_INTERVAL`."

    Design: Corner/state_machines/meeting_end_not_after_start_returns_invalid_interval
    """
    s = _active_listing_with_nda_buyer(api)
    resp = api.schedule_meeting(
        s["listing"]["id"],
        create_meeting_payload(s["buyer_a"]["id"], "2026-03-01T11:00:00Z", "2026-03-01T10:00:00Z"),
        s["hdr"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_data_room_listing_without_nda_rejected(api):
    """PRD §3.3: "When a buyer lists the documents on a listing, the server first confirms the
    buyer holds a `SIGNED` NDA on that listing; a buyer without one is refused with
    `ERR_NDA_REQUIRED`."

    Design: Corner/validations/data_room_access_without_nda_returns_error
    """
    s = fx.setup_active_listing(api)
    fx.upload_document(api, s["broker"]["id"], s["listing"]["id"])
    buyer = fx.onboard_buyer(api)  # no NDA
    resp = api.list_documents(s["listing"]["id"], make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_NDA_REQUIRED.value)
