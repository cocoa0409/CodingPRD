"""Booking creation gates: temporal validity, OCC, program posture, clock expiry."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_booking,
    create_booking,
    create_booking_payload,
    get_booking,
    get_share,
    make_owner_headers,
    set_clock,
    setup_program_with_share,
    validate_error,
    validate_success,
)


class TestDepartureTemporalGate:
    def test_booking_create_departure_in_past_rejected(self, api):
        """PRD §3.3: "the departure must lie strictly after the current clock — a
        departure at or before the present instant is rejected with
        `ERR_TEMPORAL_INVALID` (HTTP 422)."

        Design: Corner/validations/booking_create_departure_in_past_rejected
        """
        sc = setup_program_with_share(program_code="FJX-VA1", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        resp = create_booking(
            share["id"], owner["id"], cls["id"],
            scheduled_departure_utc="2026-07-01T00:00:00Z",
            estimated_block_hours=1.00,
            expected_share_version=share["version"],
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)
        assert resp.status_code == 422


class TestOptimisticConcurrencyOnCreate:
    def test_booking_create_increments_share_version_by_one(self, api):
        """PRD §3.3: "The request lands with `booking_status` `REQUESTED` and
        `billing_status` `UNBILLED`, and the share's `version` advances by one."

        Design: Corner/cross_cutting_layers/occ_share_version_increments_on_booking_create
        """
        sc = setup_program_with_share(program_code="FJX-CC1", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        before = share["version"]
        resp = api.create_booking(
            create_booking_payload(
                share["id"], cls["id"], before,
                scheduled_departure_utc="2026-09-10T15:00:00Z",
                estimated_block_hours=1.00,
            ),
            make_owner_headers(owner["id"]),
        )
        booking = validate_success(resp, 201)
        assert_booking(booking)
        assert booking["booking_status"] == "REQUESTED"
        assert booking["billing_status"] == "UNBILLED"
        after = get_share(share["id"])["version"]
        assert after == before + 1, (
            f"share version must advance by exactly one per mutation: {before} -> {after}"
        )

    def test_stale_share_version_rejected_on_second_create(self, api):
        """PRD §2.7: "Creating a booking request (`POST /bookings`) requires
        `expected_share_version`, carrying the funding share's `version` as the client
        last observed it. A mismatch with the share's current `version` — for example
        because another booking was confirmed or cancelled against the same share and
        legitimately moved its remaining-hours balance — is rejected with
        `ERR_STALE_SHARE_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_share_version_covered
        """
        sc = setup_program_with_share(program_code="FJX-ER1", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        stale_v = share["version"]
        # First create succeeds and bumps the share's version
        first = create_booking(
            share["id"], owner["id"], cls["id"],
            "2026-09-10T15:00:00Z", 1.00, expected_share_version=stale_v,
        )
        assert first.status_code == 201, f"Setup step failed: {first.text}"
        assert get_share(share["id"])["version"] == stale_v + 1
        # Replay with the superseded version
        second = create_booking(
            share["id"], owner["id"], cls["id"],
            "2026-09-11T15:00:00Z", 1.00, expected_share_version=stale_v,
        )
        validate_error(second, ApiErrorId.ERR_STALE_SHARE_VERSION)
        assert second.status_code == 412


class TestProgramPostureGate:
    def test_booking_create_rejected_under_winding_down(self, api):
        """PRD §2.9: "A `ProgramAdmin` may move a program from `ACTIVE` or `SUSPENDED`
        into `WINDING_DOWN`, after which the creation of new shares and new booking
        requests is rejected, every booking still in `REQUESTED` is expired, and every
        transfer listing still `LISTED` cascades to `EXPIRED`."
        PRD §2.8: "The program-posture gate, applied to booking creation, booking
        confirmation, listing creation, and listing acceptance — otherwise
        `ERR_PROGRAM_POSTURE_BLOCKS` (HTTP 409)."

        Design: Corner/errors/error_program_posture_blocks_wind_down_booking
        """
        from test_helpers import TEST_USERS as _TU

        sc = setup_program_with_share(program_code="FJX-ER3", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        wind = api.wind_down_program(sc["program"]["id"], _TU["program_admin_headers"])
        assert wind.status_code == 200, f"Setup step failed: {wind.text}"
        current_v = get_share(share["id"])["version"]
        resp = api.create_booking(
            create_booking_payload(
                share["id"], cls["id"], current_v,
                scheduled_departure_utc="2026-09-10T15:00:00Z",
                estimated_block_hours=1.00,
            ),
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_POSTURE_BLOCKS)
        assert resp.status_code == 409


class TestBookingExpiry:
    def test_requested_booking_expires_when_clock_reaches_departure(self, api):
        """PRD §3.3: "Should the clock reach `scheduled_departure_utc` while the request
        still sits in `REQUESTED`, the booking expires automatically, moving to `EXPIRED`
        with no further effect."

        Design: Corner/state_machines/booking_request_expiry_via_clock
        """
        sc = setup_program_with_share(program_code="FJX-SM2", class_code="MID")
        share, owner, cls = sc["share"], sc["owner"], sc["cls"]
        booking = create_booking(
            share["id"], owner["id"], cls["id"],
            "2026-09-10T15:00:00Z", 1.00, expected_share_version=share["version"],
        )
        booking = validate_success(booking, 201)
        set_clock("2026-09-10T15:00:00Z")
        after = get_booking(booking["id"])
        assert after["booking_status"] == "EXPIRED", (
            f"clock reaching departure must expire a REQUESTED booking, got {after['booking_status']}"
        )
        share_after = get_share(share["id"])
        assert share_after["hours_remaining_cy"] == pytest.approx(100.00, abs=0.005), (
            "an unconfirmed booking never debits the entitlement ledger"
        )
