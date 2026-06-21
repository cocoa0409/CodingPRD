"""Validation rejections: session invalid times, booking invalid dates,
self-exclusion period too short."""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    create_property,
    create_member,
    get_member_version,
    ApiErrorId,
    make_loyalty_manager_headers,
    make_member_services_headers,
    make_member_headers,
)


class TestGamingSessionInvalidTimes:
    """PRD §3.3: ended_at must be strictly greater than started_at."""

    def test_session_with_ended_before_started_returns_invalid_times(self, api):
        """PRD §3.3: "The submission is refused if the member is excluded
        (ERR_MEMBER_EXCLUDED), if ended_at is not strictly greater than
        started_at (ERR_SESSION_INVALID_TIMES), if theoretical_loss_cents
        exceeds one hundred million cents — the regulatory single-session
        reporting cap of one million US dollars — in which case the
        response is ERR_SESSION_LOSS_OVER_CAP, or if the half-open
        interval from started_at (inclusive) to ended_at (exclusive) truly
        overlaps an existing RECORDED session for the same member on the
        same property — touching at an endpoint is allowed, true overlap
        is rejected with ERR_SESSION_OVERLAP."

        Design: Corner/validations/gaming_session_invalid_times_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="T", email="t@x.com",
        )
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-01T10:00:00Z",
                "ended_at": "2026-02-01T09:00:00Z",
                "game_type": "SLOTS",
                "theoretical_loss_cents": 100,
            },
            make_member_services_headers("ms_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_INVALID_TIMES.value)


class TestCompRoomBookingInvalidDates:
    """PRD §3.6: check_out must be strictly greater than check_in."""

    def test_booking_with_check_out_equal_to_check_in_returns_invalid_dates(
        self, api,
    ):
        """PRD §3.6: "The booking is refused if the member is excluded
        (ERR_MEMBER_EXCLUDED), if the member is velocity-suspended
        (ERR_MEMBER_VELOCITY_SUSPENDED), if check_out is not strictly
        greater than check_in (ERR_BOOKING_INVALID_DATES)".

        Design: Corner/validations/comp_booking_invalid_dates_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="BI", email="bi@x.com",
        )
        v = get_member_version(mem["id"])
        resp = api.create_comp_room_booking(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "check_in": "2026-03-10T15:00:00Z",
                "check_out": "2026-03-10T15:00:00Z",
                "expected_member_version": v,
            },
            make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_INVALID_DATES.value)


class TestSelfExclusionPeriodTooShort:
    """PRD §3.7: exclusion_until - requested_at >= 365 days."""

    def test_self_exclusion_under_365_days_returns_period_too_short(self, api):
        """PRD §3.7: "The submission is refused if the member already has
        an ACTIVE SelfExclusion row (state precondition: at most one
        active exclusion at a time) or if the duration from requested_at
        to exclusion_until is less than three hundred and sixty-five days
        — the regulator-mandated minimum self-exclusion period, refused
        with ERR_EXCLUSION_PERIOD_TOO_SHORT."

        Design: Corner/validations/self_exclusion_period_too_short_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="SE", email="se@x.com",
        )
        # 4-month exclusion period — way under 365 days.
        resp = api.create_self_exclusion(
            {
                "member_id": mem["id"],
                "exclusion_until": "2026-06-01T00:00:00Z",
                "reason": "too short",
            },
            make_member_headers(mem["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EXCLUSION_PERIOD_TOO_SHORT.value)
