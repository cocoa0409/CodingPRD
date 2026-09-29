"""Letting the server pick the person: eligibility, scoring and the tie-break."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_pct,
    create_assignment,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_senior,
    read_phase,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _meridian_phase(api, **phase_overrides):
    """A client, its partner, an engagement and one phase to be filled."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    engagement = create_engagement(api, client["id"], partner["id"])
    phase = create_phase(
        api,
        engagement["id"],
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
        **phase_overrides,
    )
    return client, partner, engagement, phase


class TestRankingAndTieBreak:
    """Two candidates that score identically are separated by their rate."""

    def test_the_cheaper_of_two_identical_seniors_is_booked(self, api, manager_headers):
        """Same level, same specialism, same cap: only the bill rate differs.

        PRD 3.6: "Rather than name a person, a `SchedulingManager` may ask the
        system to pick one, supplying only the `start_date`, `end_date` and
        `allocated_hours` for the booking it wants placed on the phase. The
        selector books exactly one person — the single best fit — and creates one
        booking in `PROPOSED` with its `fit_score` recorded."

        PRD 3.6: "Candidates are ordered by `fit_score` descending. The first
        tie-break is `hourly_bill_rate` ascending, putting cheaper staff first;
        the second is `created_at` ascending. The row `id` is never used as a
        tie-break. The first candidate under that ordering is selected."

        Design: Corner/calculations/auto_staff_tie_break_selects_cheaper_senior_at_equal_fit_score
        """

        client, partner, engagement, phase = _meridian_phase(api, expected_hours=20.00)
        dearer = create_senior(api, full_name="Alex Trent", hourly_bill_rate=220.00)
        cheaper = create_senior(api, full_name="Bree Okafor", hourly_bill_rate=180.00)

        booking = validate_success(
            api.auto_staff_phase(
                phase["id"],
                manager_headers,
                start_date="2026-08-03",
                end_date="2026-08-08",
                allocated_hours=5.00,
            ),
            201,
        )

        assert booking["staff_member_id"] == cheaper["id"]
        assert booking["staff_member_id"] != dearer["id"]
        assert_pct(booking["fit_score"], 100.00)
        assert booking["staffing_status"] == "PROPOSED"

    def test_the_selected_booking_is_shaped_like_a_named_one(
        self, api, manager_headers
    ):
        """Five occupied dates, one hour a day, and a domestic rate model.

        PRD 3.6: "The remaining behaviour matches a named booking exactly: the
        server computes the new booking's `daily_hours`, `calendar_day_count`,
        `rate_model` and `review_status`, re-derives the phase's `staffed_hours`,
        `unstaffed_hours` and `staffing_status`"

        PRD 3.3: "The `rate_model` is derived from the assigned person's
        `service_center`: `ONSHORE_STANDARD` for `DOMESTIC`,
        `OFFSHORE_SHARED_SERVICE` for `OFFSHORE`."

        Design: Corner/calculations/auto_staff_tie_break_selects_cheaper_senior_at_equal_fit_score
        """

        client, partner, engagement, phase = _meridian_phase(api, expected_hours=20.00)
        create_senior(api, full_name="Alex Trent", hourly_bill_rate=220.00)
        create_senior(api, full_name="Bree Okafor", hourly_bill_rate=180.00)

        booking = validate_success(
            api.auto_staff_phase(
                phase["id"],
                manager_headers,
                start_date="2026-08-03",
                end_date="2026-08-08",
                allocated_hours=5.00,
            ),
            201,
        )

        assert_hours(booking["allocated_hours"], 5.00)
        assert booking["calendar_day_count"] == 5
        assert_hours(booking["daily_hours"], 1.00)
        assert booking["rate_model"] == "ONSHORE_STANDARD"


class TestSlackRatioDrivesTheScore:
    """The headroom component of the score is not always saturated."""

    def test_half_the_hole_worth_of_headroom_scores_eighty_five(
        self, api, manager_headers
    ):
        """Ten hours left against a fifteen-hour hole is not a full slack ratio.

        PRD 3.6: "The week's remaining headroom is that person's effective weekly
        cap for the ISO week containing the requested `start_date` minus their
        committed load in that week, rounded to two decimals. The slack ratio is
        that headroom divided by the phase's `unstaffed_hours`, rounded to four
        decimals and then capped at 1.0000 — the phase's unstaffed hours are
        guaranteed positive, because a fully staffed phase never reaches the
        selector."

        PRD 3.6: "The `fit_score` is then the sum of three components, rounded to
        two decimals: forty points always, because matching the required grade is
        an eligibility condition rather than a differentiator; a further thirty
        points when — and only when — the phase declares a non-null
        `required_industry_specialization`, which rewards specialist-demanding
        phases uniformly across their eligible candidates; and thirty points
        multiplied by the slack ratio, which favours the person with the most
        headroom relative to the hole being filled."

        Design: Corner/calculations/auto_staff_fit_score_drops_to_eighty_five_at_half_slack
        """

        client, partner, engagement, fieldwork = _meridian_phase(
            api, expected_hours=40.00
        )
        senior = create_senior(api)
        interim = create_phase(
            api,
            engagement["id"],
            phase_type="INTERIM",
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        create_assignment(
            api,
            fieldwork["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=40.00,
        )

        booking = validate_success(
            api.auto_staff_phase(
                interim["id"],
                manager_headers,
                start_date="2026-08-08",
                end_date="2026-08-10",
                allocated_hours=5.00,
            ),
            201,
        )

        assert booking["staff_member_id"] == senior["id"]
        assert_pct(booking["fit_score"], 85.00)
        assert booking["calendar_day_count"] == 2
        assert_hours(booking["daily_hours"], 2.50)

    def test_the_filled_phase_reports_the_selected_hours(self, api, manager_headers):
        """Five of twenty hours placed leaves the phase partly filled.

        PRD 3.2: "A new phase begins at `NOT_STAFFED` with `staffed_hours` 0.00
        and `unstaffed_hours` equal to its `expected_hours`; creating it refreshes
        the engagement's `staffing_completion_pct` and `schedule_risk_band` and
        increments the engagement's `version`."

        PRD 3.6: "The remaining behaviour matches a named booking exactly: the
        server computes the new booking's `daily_hours`, `calendar_day_count`,
        `rate_model` and `review_status`, re-derives the phase's `staffed_hours`,
        `unstaffed_hours` and `staffing_status`"

        Design: Corner/calculations/auto_staff_fit_score_drops_to_eighty_five_at_half_slack
        """

        client, partner, engagement, fieldwork = _meridian_phase(
            api, expected_hours=40.00
        )
        senior = create_senior(api)
        interim = create_phase(
            api,
            engagement["id"],
            phase_type="INTERIM",
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )
        create_assignment(
            api,
            fieldwork["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=40.00,
        )
        validate_success(
            api.auto_staff_phase(
                interim["id"],
                manager_headers,
                start_date="2026-08-08",
                end_date="2026-08-10",
                allocated_hours=5.00,
            ),
            201,
        )

        after = read_phase(api, interim["id"])
        assert_hours(after["staffed_hours"], 5.00)
        assert_hours(after["unstaffed_hours"], 15.00)
        assert after["staffing_status"] == "PARTIALLY_STAFFED"


class TestEmptyCandidatePool:
    """A phase nobody in the firm can fill writes nothing at all."""

    def test_a_phase_demanding_an_unavailable_grade_finds_nobody(
        self, api, manager_headers
    ):
        """A manager-grade financial-services phase in a firm of one senior.

        PRD 3.6: "The candidate pool is every staff member who satisfies all eight
        of the following. Their `level` equals the phase's `required_level`. Either
        the phase's `required_industry_specialization` is null, or their
        `industry_specialization` equals it."

        PRD 3.6: "If the pool is empty the request is refused with
        `ERR_NO_ELIGIBLE_STAFF` (HTTP 422) and **no booking row is created**."

        Design: Corner/calculations/auto_staff_with_no_matching_level_returns_no_eligible_staff
        """

        client, partner, engagement, phase = _meridian_phase(
            api,
            phase_type="REVIEW",
            expected_hours=12.00,
            required_level="MANAGER",
            required_industry_specialization="FINANCIAL_SERVICES",
        )
        create_senior(api)

        validate_error(
            api.auto_staff_phase(
                phase["id"],
                manager_headers,
                start_date="2026-08-03",
                end_date="2026-08-08",
                allocated_hours=5.00,
            ),
            ApiErrorId.NO_ELIGIBLE_STAFF.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_assignments(manager_headers, engagement_phase_id=phase["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []

        after = read_phase(api, phase["id"])
        assert after["staffing_status"] == "NOT_STAFFED"
        assert_hours(after["staffed_hours"], 0.00)
        assert_hours(after["unstaffed_hours"], 12.00)


class TestSelectorRefusesAFullPhase:
    """There must be a hole for the selector to fill."""

    def test_a_fully_staffed_phase_is_refused_even_with_a_spare_senior(
        self, api, manager_headers
    ):
        """Zero unstaffed hours stops the selector before eligibility is examined.

        PRD 3.6: "The selector refuses to run on a phase that has nothing left to
        fill: the phase must be `NOT_STAFFED` or `PARTIALLY_STAFFED` with
        `unstaffed_hours` strictly greater than 0.00, and otherwise the request is
        refused with `ERR_PHASE_FULLY_STAFFED`."

        Design: Corner/validations/auto_staff_on_fully_staffed_phase_rejected
        """

        client, partner, engagement, phase = _meridian_phase(api, expected_hours=20.00)
        senior = create_senior(api)
        create_senior(api, full_name="Dana Kirsch", hourly_bill_rate=165.00)
        create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-08",
            allocated_hours=20.00,
        )

        filled = read_phase(api, phase["id"])
        assert filled["staffing_status"] == "FULLY_STAFFED"
        assert_hours(filled["staffed_hours"], 20.00)
        assert_hours(filled["unstaffed_hours"], 0.00)

        validate_error(
            api.auto_staff_phase(
                phase["id"],
                manager_headers,
                start_date="2026-08-10",
                end_date="2026-08-15",
                allocated_hours=5.00,
            ),
            ApiErrorId.PHASE_FULLY_STAFFED.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_assignments(manager_headers, engagement_phase_id=phase["id"])
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
