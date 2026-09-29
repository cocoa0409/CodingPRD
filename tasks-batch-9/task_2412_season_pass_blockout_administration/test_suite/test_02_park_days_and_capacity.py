"""The operating calendar: capacity posture derivation and re-forecasting."""

from test_helpers import (
    DayClass,
    assert_day_counters,
    assert_day_posture,
    assert_ordered_by,
    create_park_day,
    create_program,
    forecast_park_day,
    program_admin_headers,
    validate_paginated,
)


def _park_days(api, **params):
    response = api.list_park_days(headers=program_admin_headers(), params=params or None)
    return validate_paginated(response)


class TestCapacityPostureDerivation:
    """Everything but the two inputs is derived on write."""

    def test_the_two_slot_budgets_are_derived_from_capacity_and_forecast(self, api, default_clock):
        """A 800/200 day offers a tenth of the gate and half of that per window.

        PRD: "Third, `reservation_slot_capacity` — the number of reservable slots the day
        offers as a whole — is the smaller of two quantities, and then floored at zero:
        the first quantity is one tenth of `capacity_total` truncated to a whole number,
        because the park never reserves away more than ten percent of a day's gate; the
        second is `capacity_total` less `forecast_attendance`, because the park never
        reserves away capacity the forecast has already consumed."

        Design: Corner/entities/park_day_capacity_fields_are_computed_from_the_forecast
        """
        program = create_program(api)

        day = create_park_day(
            api, program["id"], "2026-08-15", capacity_total=800, forecast_attendance=200
        )

        assert_day_posture(
            day,
            utilization=0.2500,
            day_class=DayClass.STANDARD.value,
            slot_capacity=80,
            window_capacity=40,
        )
        assert_day_counters(day, reserved=0, released=0, redeemed=0, no_show=0, remaining=80, grant=0)


class TestParkDayListing:
    """The calendar listing pages and orders as the contract pins it."""

    def test_the_listing_reports_total_count_and_has_more_across_pages(self, api, default_clock):
        """The counters describe the whole match set, not the page.

        PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
        the `meta` object of the envelope, where `total_count` is the number of records
        matching the filters before pagination is applied and `has_more` indicates whether
        records remain beyond the current page."

        Design: Corner/entities/park_day_listing_paginates_with_total_count_and_has_more
        """
        program = create_program(api)
        for calendar_date in ("2026-08-10", "2026-08-11", "2026-08-12"):
            create_park_day(api, program["id"], calendar_date)

        first_page, first_meta = _park_days(api, program_id=program["id"], limit=2)

        assert len(first_page) == 2, f"the first page should hold two days, got {len(first_page)}"
        assert first_meta["total_count"] == 3, (
            f"total_count should count all three days, got {first_meta['total_count']!r}"
        )
        assert first_meta["limit"] == 2 and first_meta["offset"] == 0, (
            f"the meta block should echo the request, got {first_meta!r}"
        )
        assert first_meta["has_more"] is True, "a third day remains beyond the first page"
        assert_ordered_by(first_page, "calendar_date")

        second_page, second_meta = _park_days(api, program_id=program["id"], limit=2, offset=2)

        assert len(second_page) == 1, f"the second page should hold one day, got {len(second_page)}"
        assert second_meta["total_count"] == 3, (
            f"total_count is independent of the page, got {second_meta['total_count']!r}"
        )
        assert second_meta["has_more"] is False, "nothing remains beyond the second page"

        _, bare_meta = _park_days(api)
        assert bare_meta["limit"] == 10 and bare_meta["offset"] == 0, (
            f"a bare call should fall back to limit 10 and offset 0, got {bare_meta!r}"
        )


class TestPostureReadsTheProgrammeThresholds:
    """The bands are programme settings, not constants of the system."""

    def test_the_same_ratio_classifies_differently_under_two_programmes(self, api, default_clock):
        """A tighter programme calls 0.8000 peak; a default programme calls it standard.

        PRD: "Second, `day_class` is selected from that ratio against the owning
        programme's two thresholds: the day is `CAPACITY_LOCKED` when its utilisation is
        greater than or equal to `capacity_lock_threshold_pct`; otherwise it is `PEAK` when
        its utilisation is greater than or equal to `capacity_peak_threshold_pct`;
        otherwise it is `STANDARD`."

        Design: Corner/calculations/capacity_posture_reads_thresholds_from_the_program_row
        """
        tight = create_program(api, park_name="Tight Ridge", capacity_peak_threshold_pct=0.80)
        loose = create_program(api, season_year=2027, park_name="Loose Ridge")
        loose_day = create_park_day(
            api, loose["id"], "2026-09-05", capacity_total=1000, forecast_attendance=800
        )

        tight_day = create_park_day(
            api, tight["id"], "2026-09-05", capacity_total=1000, forecast_attendance=800
        )

        assert_day_posture(
            tight_day,
            utilization=0.8000,
            day_class=DayClass.PEAK.value,
            slot_capacity=100,
            window_capacity=50,
        )
        assert_day_posture(
            loose_day,
            utilization=0.8000,
            day_class=DayClass.STANDARD.value,
            slot_capacity=100,
            window_capacity=50,
        )

    def test_neither_programme_locks_a_day_that_is_far_below_its_lock_threshold(
        self, api, default_clock
    ):
        """The lock band is a separate, higher threshold on the same programme row.

        PRD: "The two capacity thresholds must bracket each other and stay in band:
        `capacity_peak_threshold_pct` must be at least `0.50` and strictly below
        `capacity_lock_threshold_pct`, while `capacity_lock_threshold_pct` must be strictly
        above `capacity_peak_threshold_pct` and at most `1.20` — a forecast may legitimately
        exceed a day's nominal capacity, which is why the ceiling sits above one."

        Design: Corner/calculations/capacity_posture_reads_thresholds_from_the_program_row
        """
        tight = create_program(
            api,
            park_name="Tight Ridge",
            capacity_peak_threshold_pct=0.80,
            capacity_lock_threshold_pct=0.95,
        )

        tight_day = create_park_day(
            api, tight["id"], "2026-09-05", capacity_total=1000, forecast_attendance=800
        )

        assert tight_day["day_class"] != DayClass.CAPACITY_LOCKED.value, (
            "0.8000 sits well below a 0.95 lock threshold, got "
            f"{tight_day['day_class']!r}"
        )
        assert_day_posture(tight_day, utilization=0.8000, day_class=DayClass.PEAK.value)
        assert_day_counters(tight_day, reserved=0, remaining=100, grant=0)


class TestPeakThresholdBoundary:
    """The peak threshold is inclusive and the posture is never latched."""

    def test_utilisation_exactly_at_the_peak_threshold_classifies_the_day_peak(self, api, default_clock):
        """A ratio of 0.8500 against the default threshold of 0.85 is already PEAK.

        PRD: "Both thresholds are inclusive, so a utilisation exactly equal to the peak
        threshold classifies the day `PEAK`, not `STANDARD`, and a utilisation exactly
        equal to the lock threshold classifies it `CAPACITY_LOCKED`."

        Design: Difficulty/boundary_precision_check/park_day_peak_threshold_at_exactly_85_percent
        """
        program = create_program(api)
        day = create_park_day(
            api, program["id"], "2026-09-12", capacity_total=1000, forecast_attendance=849
        )
        assert_day_posture(day, utilization=0.8490, day_class=DayClass.STANDARD.value)

        raised = forecast_park_day(api, day["id"], 850)

        assert_day_posture(
            raised,
            utilization=0.8500,
            day_class=DayClass.PEAK.value,
            slot_capacity=100,
            window_capacity=50,
        )
        assert_day_counters(raised, reserved=0, remaining=100)

    def test_dropping_one_attendee_below_the_threshold_returns_the_day_to_standard(
        self, api, default_clock
    ):
        """The class is re-derived on every forecast and may move in either direction.

        PRD: "A forecast update supplies a new `forecast_attendance` and may optionally
        also supply a replacement `capacity_total`; the day's whole posture is then
        re-derived, its `version` increments by 1, and `day_class` may move in **either**
        direction any number of times over the season."

        Design: Difficulty/boundary_precision_check/park_day_peak_threshold_at_exactly_85_percent
        """
        program = create_program(api)
        day = create_park_day(
            api, program["id"], "2026-09-12", capacity_total=1000, forecast_attendance=849
        )
        peak = forecast_park_day(api, day["id"], 850)
        assert_day_posture(peak, day_class=DayClass.PEAK.value)

        lowered = forecast_park_day(api, day["id"], 849)

        assert_day_posture(
            lowered,
            utilization=0.8490,
            day_class=DayClass.STANDARD.value,
            slot_capacity=100,
            window_capacity=50,
        )
