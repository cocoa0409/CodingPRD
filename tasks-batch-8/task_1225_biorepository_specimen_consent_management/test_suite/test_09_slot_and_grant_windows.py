"""Temporal overlap windows: half-open slot reservations vs closed grant windows + buffer."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    COORD_HEADERS,
    LAB_HEADERS,
    create_donor_with_consent,
    create_unit_with_slot,
    create_key_for_specimen,
    create_grant_for_key,
    book_reservation,
    accession_specimen,
    create_returned_kit,
)


class TestSlotReservationHalfOpenAdjacency:
    """Half-open [starts_at, ends_at) slot windows: touching is allowed, overlap is not."""

    def _setup(self, api):
        _, slot = create_unit_with_slot(unit_code="FRZ-OV1")
        book_reservation(slot["id"], "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
                         purpose="MAINTENANCE")
        return slot

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §3.4: "Booking is rejected with `ERR_SLOT_RESERVATION_OVERLAP`
        (HTTP 409) when the new window overlaps any existing `BOOKED` reservation on
        the same slot; back-to-back adjacency — the new `starts_at` landing exactly on
        an existing reservation's `ends_at` — is allowed, because half-open windows
        that merely touch do not overlap."

        Design: Difficulty/resource_temporal_overlap/slot_reservation_half_open_adjacency
        """
        slot = self._setup(api)
        resp = api.create_slot_reservation(
            slot["id"],
            {"starts_at": "2026-06-01T12:00:00Z", "ends_at": "2026-06-01T14:00:00Z",
             "purpose": "AUDIT"},
            LAB_HEADERS,
        )
        validate_success(resp, expected_status=201)
        reservations = validate_success(api.list_slot_reservations(slot["id"], LAB_HEADERS))
        booked = [r for r in reservations if r["status"] == "BOOKED"]
        assert len(booked) == 2, f"both reservations must stand, got {len(booked)}"

    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.4: "Reservation windows are half-open: the start instant is included,
        the end instant is excluded, and `ends_at` must be strictly after `starts_at`
        or the request fails shape validation as `ERR_INVALID_REQUEST`."

        Design: Difficulty/resource_temporal_overlap/slot_reservation_half_open_adjacency
        """
        slot = self._setup(api)
        resp = api.create_slot_reservation(
            slot["id"],
            {"starts_at": "2026-06-01T11:59:00Z", "ends_at": "2026-06-01T13:00:00Z",
             "purpose": "TRANSFER_HOLD"},
            LAB_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_RESERVATION_OVERLAP)


class TestKeyGrantClosedIntervalWithBuffer:
    """Closed [starts_at, ends_at] grant windows with a mandatory 24h buffer."""

    def _setup(self, api):
        donor, consent = create_donor_with_consent(allow_reidentification=True)
        kit = create_returned_kit(donor["id"])
        specimen = accession_specimen(donor["id"], kit["id"], consent["id"],
                                      initial_volume_ml=50.0)
        key = create_key_for_specimen(specimen["id"])
        # Existing closed-window grant [2026-06-01T09:00, 2026-06-01T17:00].
        create_grant_for_key(key["id"], grantee_user_id="officer-a",
                             starts_at="2026-06-01T09:00:00Z",
                             ends_at="2026-06-01T17:00:00Z")
        return key

    def test_touching_and_short_gap_grants_rejected(self, api):
        """PRD §3.8: "Because the windows are closed, touching endpoints already count
        as overlap, and the rule goes further: a new grant whose window overlaps an
        existing grant on the same key, or that leaves a gap of less than 24 hours on
        either side of an existing grant on the same key, is rejected with
        `ERR_GRANT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/key_grant_closed_interval_with_buffer
        """
        key = self._setup(api)
        # Touching: new starts exactly at the existing ends_at.
        resp = api.create_key_access_grant(
            key["id"],
            {"grantee_user_id": "officer-b", "starts_at": "2026-06-01T17:00:00Z",
             "ends_at": "2026-06-01T19:00:00Z", "purpose": "touching window"},
            COORD_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW_CONFLICT)
        # 23-hour gap (2026-06-02T16:00 is 23h after 2026-06-01T17:00).
        resp = api.create_key_access_grant(
            key["id"],
            {"grantee_user_id": "officer-b", "starts_at": "2026-06-02T16:00:00Z",
             "ends_at": "2026-06-02T18:00:00Z", "purpose": "23 hour gap"},
            COORD_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW_CONFLICT)

    def test_exactly_24_hour_gap_allowed(self, api):
        """PRD §3.8: "a new grant whose window overlaps an existing grant on the same
        key, or that leaves a gap of less than 24 hours on either side of an existing
        grant on the same key, is rejected with `ERR_GRANT_WINDOW_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/key_grant_closed_interval_with_buffer
        """
        key = self._setup(api)
        # Exactly 24h after the existing window ends: buffer satisfied at equality.
        resp = api.create_key_access_grant(
            key["id"],
            {"grantee_user_id": "officer-b", "starts_at": "2026-06-02T17:00:00Z",
             "ends_at": "2026-06-03T09:00:00Z", "purpose": "exactly 24 hour gap"},
            COORD_HEADERS,
        )
        validate_success(resp, expected_status=201)
        grants = validate_success(api.list_key_access_grants(key["id"], COORD_HEADERS))
        active = [g for g in grants if g["status"] == "ACTIVE"]
        assert len(active) == 2, f"exactly 2 ACTIVE grants expected, got {len(active)}"
