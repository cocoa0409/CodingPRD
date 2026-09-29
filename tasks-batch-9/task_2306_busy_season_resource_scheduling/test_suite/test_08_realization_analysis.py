"""Realization: two variants, one pinned rounding order, and conserved hours."""

from __future__ import annotations

from test_helpers import (
    assert_hours,
    assert_money,
    assert_pct,
    create_assignment,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_senior,
    create_time_entry,
    drive_assignment_to_active,
    read_assignment,
    read_engagement,
    read_phase,
    read_realization,
    read_staff,
    set_clock,
    validate_success,
)


def _booked_and_logged_world(
    api,
    client_name="Meridian Manufacturing",
    senior_name="Sam Oyelaran",
    hourly_bill_rate=180.00,
    budget_fee_amount=6000.00,
    expected_hours=45.00,
    allocated_hours=45.00,
    end_date="2026-08-10",
    phase_type="FIELDWORK",
    daily_logs=(),
    **phase_overrides,
):
    """One active booking on one phase, plus whatever hours were logged against it."""

    set_clock(api, "2026-08-03T09:00:00Z")
    client = create_client(api, name=client_name)
    partner = create_partner(api)
    senior = create_senior(
        api, full_name=senior_name, hourly_bill_rate=hourly_bill_rate
    )
    engagement = create_engagement(
        api, client["id"], partner["id"], budget_fee_amount=budget_fee_amount
    )
    phase = create_phase(
        api,
        engagement["id"],
        phase_type=phase_type,
        expected_hours=expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
        **phase_overrides,
    )
    assignment = create_assignment(
        api,
        phase["id"],
        senior["id"],
        start_date="2026-08-03",
        end_date=end_date,
        allocated_hours=allocated_hours,
    )
    drive_assignment_to_active(api, engagement["id"], phase["id"], assignment["id"])
    for work_date, hours in daily_logs:
        create_time_entry(
            api, assignment["id"], senior["id"], work_date=work_date, hours=hours
        )
    return {
        "client": client,
        "partner": partner,
        "senior": senior,
        "engagement": engagement,
        "phase": phase,
        "assignment": assignment,
    }


class TestTheTwoVariantsDiverge:
    """Booked hours and logged hours are different input sets, not different weights."""

    def test_booked_and_logged_hours_produce_two_different_percentages(self, api):
        """Forty-five booked against forty-six logged, in one and the same response.

        PRD 3.9: "The **provisional** variant, surfaced as
        `realization_pct_provisional`, values what has been *booked*. Its input is
        every booking on this engagement's phases whose `staffing_status` is
        `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED`; released bookings are
        excluded."

        PRD 3.9: "The **final** variant, surfaced as `realization_pct_final`,
        values what was actually *logged*. Its input is every time entry whose
        booking belongs to this engagement and whose booking's `staffing_status` is
        `CONFIRMED`, `ACTIVE` or `COMPLETED`"

        PRD 3.9: "The same records support two variants that diverge on identical
        data, and both are stored on the engagement."

        Design: Difficulty/dual_variant_calc/realization_provisional_vs_final_diverges_on_same_engagement
        """

        world = _booked_and_logged_world(
            api,
            daily_logs=(
                ("2026-08-03", 16.00),
                ("2026-08-04", 16.00),
                ("2026-08-05", 14.00),
            ),
        )

        analysis = read_realization(api, world["engagement"]["id"])
        assert_hours(analysis["committed_hours_total"], 45.00)
        assert_hours(analysis["logged_hours_total"], 46.00)
        assert_pct(analysis["realization_pct_provisional"], 74.07)
        assert_pct(analysis["realization_pct_final"], 72.46)
        assert round(float(analysis["realization_pct_final"]), 2) != round(
            float(analysis["realization_pct_provisional"]), 2
        )

    def test_each_variant_reports_its_own_standard_value(self, api):
        """Eight thousand one hundred booked; eight thousand two hundred eighty logged.

        PRD 3.9: "Every booking has an **effective rate** — the assigned person's
        `hourly_bill_rate` multiplied by a factor for the staffing model, rounded
        to two decimals. Onshore work carries a factor of 1.00; offshore and
        shared-service work is valued at 0.55, a little over half the standard
        rate, which is exactly why the staffing model changes the reported answer."

        PRD 3.9: "A dedicated computed read reports the full analysis for one
        engagement, split by staffing model: `engagement_id`,
        `budget_fee_amount`, `committed_hours_total`, `logged_hours_total`,
        `standard_value_provisional`, `realization_pct_provisional`,
        `standard_value_final`, `realization_pct_final`, `onshore_standard_value`
        and `offshore_standard_value`."

        Design: Difficulty/dual_variant_calc/realization_provisional_vs_final_diverges_on_same_engagement
        """

        world = _booked_and_logged_world(
            api,
            daily_logs=(
                ("2026-08-03", 16.00),
                ("2026-08-04", 16.00),
                ("2026-08-05", 14.00),
            ),
        )

        analysis = read_realization(api, world["engagement"]["id"])
        assert analysis["engagement_id"] == world["engagement"]["id"]
        assert_money(analysis["budget_fee_amount"], 6000.00)
        assert_money(analysis["standard_value_provisional"], 8100.00)
        assert_money(analysis["standard_value_final"], 8280.00)
        assert_money(analysis["offshore_standard_value"], 0.00)


class TestRoundingOrderInTheFinalVariant:
    """Round each line, then sum — never the other way round."""

    def _three_thirds(self, api):
        return _booked_and_logged_world(
            api,
            client_name="Corvid Metals",
            senior_name="Dana Whitfield",
            hourly_bill_rate=183.75,
            budget_fee_amount=1775.00,
            expected_hours=10.00,
            allocated_hours=10.00,
            end_date="2026-08-06",
            phase_type="WRAP_UP",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
            daily_logs=(
                ("2026-08-03", 3.33),
                ("2026-08-04", 3.33),
                ("2026-08-05", 3.33),
            ),
        )

    def test_three_logged_lines_sum_to_the_line_rounded_total(self, api):
        """Each 611.89 line adds up to 1835.67, not the 1835.66 of a single rounding.

        PRD 3.9: "It draws **one line per time entry**: the entry's `hours`
        multiplied by the effective rate of its booking, rounded to two decimals.
        Those per-entry lines are summed and the sum rounded to two decimals to
        give the final standard value, and the percentage is computed the same
        way."

        PRD 3.9: "**The rounding order is pinned in both**: round each line first,
        then sum. Summing the raw products and rounding once at the end is a
        different and rejected reading — three entries of 3.33 hours at an
        effective rate of 183.75 give 1835.67 when each line is rounded first and
        1835.66 when the sum is rounded once, and that one-cent difference shifts
        the reported percentage."

        Design: Difficulty/combinatorial_formula/realization_final_rounds_each_time_entry_before_summing
        """

        world = self._three_thirds(api)

        booking = read_assignment(api, world["assignment"]["id"])
        assert booking["calendar_day_count"] == 3
        assert_hours(booking["daily_hours"], 3.33)

        analysis = read_realization(api, world["engagement"]["id"])
        assert_hours(analysis["logged_hours_total"], 9.99)
        assert_money(analysis["standard_value_final"], 1835.67)
        assert round(float(analysis["standard_value_final"]), 2) != 1835.66

    def test_the_one_cent_difference_moves_the_reported_percentage(self, api):
        """A fee of 1775.00 over 1835.67 is 96.69 percent, and over 1835.66 it is not.

        PRD 3.9: "Those per-booking lines are summed and the sum rounded to two
        decimals to give the provisional standard value; the percentage is the
        engagement's `budget_fee_amount` divided by that value, multiplied by 100,
        rounded to two decimals."

        PRD 3.9: "**The rounding order is pinned in both**: round each line first,
        then sum. Summing the raw products and rounding once at the end is a
        different and rejected reading — three entries of 3.33 hours at an
        effective rate of 183.75 give 1835.67 when each line is rounded first and
        1835.66 when the sum is rounded once, and that one-cent difference shifts
        the reported percentage."

        Design: Difficulty/combinatorial_formula/realization_final_rounds_each_time_entry_before_summing
        """

        world = self._three_thirds(api)

        analysis = read_realization(api, world["engagement"]["id"])
        assert_pct(analysis["realization_pct_final"], 96.69)
        assert round(float(analysis["realization_pct_final"]), 2) != 96.70
        assert_money(analysis["standard_value_provisional"], 1837.50)
        assert_pct(analysis["realization_pct_provisional"], 96.60)


class TestStaffedPlusUnstaffedIsConserved:
    """Two mutations of opposite sign leave the phase identity intact."""

    def _two_bookings_on_one_phase(self, api):
        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=45.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
            required_industry_specialization=None,
            requires_cpa_licensed=None,
        )
        first = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=20.00,
        )
        second = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=25.00,
        )
        return {
            "senior": senior,
            "engagement": engagement,
            "phase": phase,
            "first": first,
            "second": second,
        }

    def test_scope_expansion_reopens_the_hole_without_touching_a_booking(
        self, api, manager_headers
    ):
        """Expected rises to sixty, staffed stays at forty-five, and the gap is fifteen.

        PRD 3.2: "The phase's `expected_hours` rises by that amount, the staffing
        figures and status are re-derived — which is the one path by which a
        `FULLY_STAFFED` phase falls back to `PARTIALLY_STAFFED` without any booking
        being touched — the engagement's `scope_change_count` rises by one, its
        `staffing_completion_pct` and `schedule_risk_band` are recomputed, and the
        phase's `version` increments."

        PRD 3.2: "Its `unstaffed_hours` is the expected hours minus the staffed
        hours, floored at 0.00 and rounded to two decimals; the two therefore add
        back to exactly `expected_hours` whenever staffing has not overshot."

        Design: Difficulty/compensating_invariant/phase_staffed_plus_unstaffed_equals_expected_across_scope_expansion_and_release
        """

        world = self._two_bookings_on_one_phase(api)

        expanded = validate_success(
            api.expand_phase_scope(
                world["phase"]["id"],
                manager_headers,
                additional_expected_hours=15.00,
                reason_note="client added two inventory locations",
            )
        )
        assert_hours(expanded["expected_hours"], 60.00)
        assert_hours(expanded["staffed_hours"], 45.00)
        assert_hours(expanded["unstaffed_hours"], 15.00)
        assert (
            round(float(expanded["staffed_hours"]) + float(expanded["unstaffed_hours"]), 2)
            == 60.00
        )
        assert expanded["staffing_status"] == "PARTIALLY_STAFFED"

        engagement_after = read_engagement(api, world["engagement"]["id"])
        assert engagement_after["scope_change_count"] == 1
        assert_pct(engagement_after["staffing_completion_pct"], 75.00)

    def test_a_release_on_top_of_the_expansion_still_adds_back_to_expected(
        self, api, manager_headers
    ):
        """Twenty staffed and forty unstaffed against the same sixty expected hours.

        PRD 3.2: "A phase's `staffed_hours` is the sum of `allocated_hours` over
        its bookings in `PROPOSED`, `CONFIRMED`, `ACTIVE` or `COMPLETED` — released
        bookings are excluded — rounded to two decimals."

        PRD 3.2: "Otherwise it takes the smaller of the staffed total and the
        expected total, divides by the expected total, multiplies by 100 and rounds
        to two decimals — so over-staffed phases cannot push the figure above
        100.00."

        Design: Difficulty/compensating_invariant/phase_staffed_plus_unstaffed_equals_expected_across_scope_expansion_and_release
        """

        world = self._two_bookings_on_one_phase(api)
        validate_success(
            api.expand_phase_scope(
                world["phase"]["id"],
                manager_headers,
                additional_expected_hours=15.00,
                reason_note="client added two inventory locations",
            )
        )

        released = validate_success(
            api.release_assignment(
                world["second"]["id"],
                manager_headers,
                reason_note="senior reallocated to a filing-deadline client",
            )
        )
        assert released["staffing_status"] == "RELEASED"

        phase_after = read_phase(api, world["phase"]["id"])
        assert_hours(phase_after["expected_hours"], 60.00)
        assert_hours(phase_after["staffed_hours"], 20.00)
        assert_hours(phase_after["unstaffed_hours"], 40.00)
        assert (
            round(
                float(phase_after["staffed_hours"])
                + float(phase_after["unstaffed_hours"]),
                2,
            )
            == 60.00
        )
        assert phase_after["staffing_status"] == "PARTIALLY_STAFFED"

        engagement_after = read_engagement(api, world["engagement"]["id"])
        assert_pct(engagement_after["staffing_completion_pct"], 33.33)

        assert_hours(
            read_staff(api, world["senior"]["id"])["committed_hours_current_week"], 20.02
        )

        survivor = read_assignment(api, world["first"]["id"])
        assert survivor["staffing_status"] == "PROPOSED"
        assert_hours(survivor["daily_hours"], 2.86)


class TestOverstaffingIsClamped:
    """Booking more than the phase expects never produces a negative or a surplus."""

    def test_thirty_hours_against_twenty_expected_clamps_both_readings(
        self, api, manager_headers
    ):
        """Unstaffed hours floor at zero and completion stops at a hundred percent.

        PRD 3.2: "Its `unstaffed_hours` is the expected hours minus the staffed
        hours, floored at 0.00 and rounded to two decimals; the two therefore add
        back to exactly `expected_hours` whenever staffing has not overshot."

        PRD 3.2: "Unless the phase has been frozen by starting it, the status is
        then re-derived: `NOT_STAFFED` when staffed hours are exactly 0.00,
        `FULLY_STAFFED` when staffed hours are greater than or equal to expected
        hours (exact equality counts as fully staffed), and `PARTIALLY_STAFFED` in
        every other case."

        PRD 3.2: "Otherwise it takes the smaller of the staffed total and the
        expected total, divides by the expected total, multiplies by 100 and rounds
        to two decimals — so over-staffed phases cannot push the figure above
        100.00."

        Design: Corner/calculations/overstaffed_phase_clamps_unstaffed_hours_and_completion
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        senior = create_senior(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        phase = create_phase(
            api,
            engagement["id"],
            expected_hours=20.00,
            window_start_date="2026-08-03",
            window_end_date="2026-08-31",
        )

        booking = create_assignment(
            api,
            phase["id"],
            senior["id"],
            start_date="2026-08-03",
            end_date="2026-08-10",
            allocated_hours=30.00,
        )
        assert booking["calendar_day_count"] == 7
        assert_hours(booking["daily_hours"], 4.29)

        phase_after = read_phase(api, phase["id"])
        assert_hours(phase_after["staffed_hours"], 30.00)
        assert_hours(phase_after["unstaffed_hours"], 0.00)
        assert phase_after["staffing_status"] == "FULLY_STAFFED"

        engagement_after = read_engagement(api, engagement["id"])
        assert_pct(engagement_after["staffing_completion_pct"], 100.00)
        assert round(float(engagement_after["staffing_completion_pct"]), 2) != 150.00
