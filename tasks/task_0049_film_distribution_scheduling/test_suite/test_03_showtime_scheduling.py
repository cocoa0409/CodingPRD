"""Showtime scheduling: block_minutes computation, format match,
region/tier strategy, screen time conflict with cleaning buffer,
operating hours, and competing-film peak coordination.

Covers PRD §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_PEAK_END_MIN,
    DEFAULT_PEAK_START_MIN,
    DEFAULT_PRESALE_OPENS_AT,
    DEFAULT_REGION,
    ALT_REGION,
    advance_clock,
    api_client,
    assert_showtime,
    create_film,
    create_screen,
    create_showtime,
    create_showtime_payload,
    make_cinema_ops_headers,
    setup_basic_org,
    setup_released_film,
    validate_error,
    validate_success,
)


# =========================================================================
# block_minutes computation
# =========================================================================
class TestShowtimeBlockMinutes:

    @pytest.mark.parametrize("fmt,expected_setup", [
        ("2D", 0),
        ("3D", 3),
        ("IMAX", 5),
    ])
    def test_block_minutes_for_format(self, api, fmt, expected_setup):
        """PRD §3.4: 'The base length of the show block is the film's
        duration_minutes plus the screen's trailer_minutes plus the
        screen's ad_minutes. To that base, a format-specific setup
        overhead is added: 5 minutes for IMAX, 3 minutes for 3D, and 0
        minutes for 2D. The resulting sum is stored on the showtime as
        block_minutes. The derived end_minute is exactly start_minute
        plus block_minutes'.

        Claim: block_minutes = duration + trailer + ad + format_setup.
        """
        duration = 120
        trailer = 10
        ad = 5
        start = 600
        base = setup_released_film(
            duration_minutes=duration,
            format=fmt,
            supported_formats=[fmt],
            trailer_minutes=trailer,
            ad_minutes=ad,
            operating_start_minute=0, operating_end_minute=1440,
        )
        showtime = create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=start,
        )
        expected_block = duration + trailer + ad + expected_setup
        assert showtime["block_minutes"] == expected_block, (
            f"PRD §3.4: block_minutes for {fmt} should be {expected_block}, "
            f"got {showtime['block_minutes']}"
        )
        assert showtime["end_minute"] == start + expected_block


# =========================================================================
# Format matching
# =========================================================================
class TestFormatMismatch:

    def test_format_not_supported_on_screen(self, api):
        """PRD §3.4: 'first the film's format must appear in the screen's
        supported_formats array, or the response is ERR_SCREEN_FORMAT_MISMATCH
        (422).'

        Claim: showtime for IMAX film on a 2D-only screen ->
        ERR_SCREEN_FORMAT_MISMATCH.
        """
        base = setup_released_film(
            duration_minutes=90, format="IMAX",
            supported_formats=["2D"],
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=600,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SCREEN_FORMAT_MISMATCH.value)


# =========================================================================
# Region strategy and tier caps
# =========================================================================
class TestRegionStrategy:

    def test_region_code_not_in_allowed_regions(self, api):
        """PRD §3.4: 'the cinema's region_code must be present in the
        film's region_strategy.allowed_regions ... either failure returns
        ERR_REGION_STRATEGY_VIOLATION (422).'

        Claim: cinema in region B but film.region_strategy allows only
        region A -> ERR_REGION_STRATEGY_VIOLATION.
        """
        base = setup_released_film(
            region_strategy={
                "allowed_regions": [DEFAULT_REGION],
                "tier_caps": {"TIER_1": 5, "TIER_2": 5, "TIER_3": 5},
            },
            region_code=ALT_REGION,  # cinema in REG_B
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=600,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REGION_STRATEGY_VIOLATION.value)


# =========================================================================
# Screen time conflict and cleaning buffer
# =========================================================================
class TestScreenTimeConflict:
    """PRD §3.4: 'the half-open interval starting at the other show's
    start_minute and running through that show's end_minute plus the
    screen's cleaning_interval_minutes (the cleaning buffer is attached
    to the right side of the earlier showtime) must not overlap with the
    proposed half-open interval [start_minute, end_minute); any overlap
    returns ERR_SCREEN_TIME_CONFLICT (409).'"""

    def test_overlap_rejected(self, api):
        """Claim: a second show starting within the buffered interval of
        an earlier show on the same screen is rejected with
        ERR_SCREEN_TIME_CONFLICT.
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            cleaning_interval_minutes=15,
            operating_start_minute=0, operating_end_minute=1440,
        )
        # block = 90 + 10 + 5 + 0 = 105; end = 705 ; buffered-end = 720.
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=600,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=710,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SCREEN_TIME_CONFLICT.value)

    def test_exact_buffered_boundary_allowed(self, api):
        """PRD §3.4: 'must not overlap with the proposed half-open
        interval [start_minute, end_minute)' -- the next show may start
        exactly at end_minute + cleaning_interval_minutes.

        Claim: start_minute == earlier.end_minute +
        cleaning_interval_minutes succeeds.
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            cleaning_interval_minutes=15,
            operating_start_minute=0, operating_end_minute=1440,
        )
        # block = 105; end = 705; first allowed = 705 + 15 = 720.
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=600,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=720,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert_showtime(data)


# =========================================================================
# Operating hours
# =========================================================================
class TestOperatingHours:
    """PRD §3.4: 'start_minute must be at least operating_start_minute,
    and end_minute must be no greater than operating_end_minute -- note
    the right boundary is inclusive on the show's end, so a film that
    finishes exactly at operating_end_minute is admitted, while a film
    that finishes one minute later is rejected with
    ERR_OUTSIDE_OPERATING_HOURS (422).'"""

    def test_end_exactly_at_operating_end_allowed(self, api):
        """Claim: end_minute == operating_end_minute is admitted (right
        boundary inclusive on the show's end).
        """
        base = setup_released_film(
            duration_minutes=85, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=600, operating_end_minute=700,
        )
        # block = 85 + 10 + 5 + 0 = 100; start=600 → end=700 == operating_end.
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=600,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_success(res, expected_status=201)

    def test_end_one_past_operating_end_rejected(self, api):
        """Claim: end_minute == operating_end_minute + 1 is rejected
        ERR_OUTSIDE_OPERATING_HOURS.
        """
        base = setup_released_film(
            duration_minutes=86, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=600, operating_end_minute=700,
        )
        # block = 86 + 10 + 5 + 0 = 101; start=600 → end=701 > operating_end.
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=600,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_OUTSIDE_OPERATING_HOURS.value)

    def test_start_before_operating_start_rejected(self, api):
        """PRD §3.4: 'start_minute must be at least operating_start_minute'.

        Claim: start_minute < operating_start_minute ->
        ERR_OUTSIDE_OPERATING_HOURS.
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=600, operating_end_minute=1200,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=599,
        )
        res = api.create_showtime(
            base["screen"]["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_OUTSIDE_OPERATING_HOURS.value)


# =========================================================================
# Competing-film peak coordination
# =========================================================================
class TestCompetingFilmConflict:
    """PRD §3.4: 'counting only point-membership of start_minute against
    the cinema's closed-closed peak window inclusion (a show's
    start_minute is in the peak window if it lies between
    peak_window_start_minute and peak_window_end_minute inclusive on
    both ends, despite the half-open semantics used for the peak window
    definition elsewhere), at most one showtime per distributor_id per
    business_date is permitted to start inside that window for the
    cinema; the second start in the window from the same distributor is
    rejected with ERR_COMPETING_FILM_CONFLICT (409).'"""

    def test_second_film_same_distributor_peak_rejected(self, api):
        """Claim: a second showtime for the same distributor on the same
        business_date with start_minute inside the cinema's peak window
        is rejected with ERR_COMPETING_FILM_CONFLICT.
        """
        base = setup_released_film(
            duration_minutes=90, format="2D",
            supported_formats=["2D"],
            trailer_minutes=10, ad_minutes=5,
            operating_start_minute=0, operating_end_minute=1440,
            peak_window_start_minute=DEFAULT_PEAK_START_MIN,
            peak_window_end_minute=DEFAULT_PEAK_END_MIN,
        )
        # First showtime inside peak window (1080..1380].
        create_showtime(
            base["screen"], base["cinema"], base["film"],
            start_minute=1100, business_date=DEFAULT_BUSINESS_DATE,
        )
        # Add a SECOND screen for the same cinema (same distributor's
        # film) to avoid screen-conflict from masking the peak rule.
        screen2 = create_screen(
            base["cinema"],
            supported_formats=["2D"],
            operating_start_minute=0, operating_end_minute=1440,
            cleaning_interval_minutes=15,
            trailer_minutes=10, ad_minutes=5, seat_capacity=100,
        )
        payload = create_showtime_payload(
            film_id=base["film"]["id"], start_minute=1200,
            business_date=DEFAULT_BUSINESS_DATE,
        )
        res = api.create_showtime(
            screen2["id"], payload,
            make_cinema_ops_headers(base["cinema"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_COMPETING_FILM_CONFLICT.value)
