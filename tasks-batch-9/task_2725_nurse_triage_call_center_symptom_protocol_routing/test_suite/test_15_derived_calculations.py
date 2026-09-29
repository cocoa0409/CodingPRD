"""Clock-derived values: after-hours flag, licence status, shift status."""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_instant,
    assert_percentage,
    assert_whole_minutes,
)


@pytest.fixture
def two_practices_with_identical_office_hours(world):
    """Same 13:00-22:00 hours, opposite weekend policies, B covered.

    Both coverage windows are drafted and activated while the clock still
    reads 2026-07-30T12:00:00Z, before it is moved to any instant under test.
    """
    world.set_clock("2026-07-30T12:00:00Z")
    practice_a = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="Practice A Weekday Only",
                weekend_is_after_hours=False,
            ),
            world.admin,
        )
    )
    practice_b = get_success_data(
        world.api.create_practice(
            f.practice_payload(
                name="Practice B Weekend Covered",
                weekend_is_after_hours=True,
            ),
            world.admin,
        )
    )
    weekend = world.create_coverage_window(
        practice_b["id"],
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-03T00:00:00Z",
        coverage_kind="WEEKEND",
    )
    world.activate_coverage_window(weekend["id"])
    nights = world.create_coverage_window(
        practice_b["id"],
        start_utc="2026-08-03T22:00:00Z",
        end_utc="2026-08-04T02:00:00Z",
        coverage_kind="NIGHTS",
    )
    world.activate_coverage_window(nights["id"])
    return practice_a, practice_b, weekend, nights


class TestAfterHoursFlagFollowsTheOwningPractice:
    def test_the_same_saturday_instant_splits_the_two_practices(
        self, world, two_practices_with_identical_office_hours
    ):
        """PRD §3.3: "The call is after-hours when either of two conditions holds:
        the practice has `weekend_is_after_hours` set to true and the calendar date
        of the clock is ISO weekday six or seven; or the minute-of-day does not lie
        in the half-open window that begins at the opening minute inclusive and ends
        at the closing minute exclusive."

        Design: Corner/calculations/after_hours_flag_follows_the_practices_own_weekend_policy_and_the_half_open_office_window
        """
        practice_a, practice_b, _, _ = two_practices_with_identical_office_hours
        world.set_clock("2026-08-01T14:30:00Z")

        call_a = world.open_call(
            practice_a["id"],
            caller_name="Saturday Caller A",
            caller_phone="+14155550101",
            reason_text="saturday, practice a",
        )
        call_b = world.open_call(
            practice_b["id"],
            caller_name="Saturday Caller B",
            caller_phone="+14155550102",
            reason_text="saturday, practice b",
        )

        assert call_a["is_after_hours"] is False, (
            "minute-of-day 870 is inside 780..1320 and the weekend flag is off"
        )
        assert call_b["is_after_hours"] is True

    def test_the_closing_minute_is_exclusive_on_a_weekday(
        self, world, two_practices_with_identical_office_hours
    ):
        """PRD §3.3: "a Monday call at exactly 22:00 has minute-of-day 1320, which is
        not strictly below the closing minute 1320, so it too is after-hours. The
        closing boundary is exclusive and the opening boundary is inclusive."

        Design: Corner/calculations/after_hours_flag_follows_the_practices_own_weekend_policy_and_the_half_open_office_window
        """
        _, practice_b, _, _ = two_practices_with_identical_office_hours

        world.set_clock("2026-08-03T21:59:00Z")
        before_close = world.open_call(
            practice_b["id"],
            caller_name="Monday Caller Before Close",
            caller_phone="+14155550103",
            reason_text="one minute before close",
        )
        world.set_clock("2026-08-03T22:00:00Z")
        at_close = world.open_call(
            practice_b["id"],
            caller_name="Monday Caller At Close",
            caller_phone="+14155550104",
            reason_text="exactly at the close minute",
        )

        assert before_close["is_after_hours"] is False
        assert at_close["is_after_hours"] is True

    def test_both_intake_rows_are_written_at_intake(
        self, world, two_practices_with_identical_office_hours
    ):
        """PRD §3.3: "First, `is_after_hours` is computed and then **frozen** for the
        life of the call; later clock advances never re-flip it."

        Design: Corner/calculations/after_hours_flag_follows_the_practices_own_weekend_policy_and_the_half_open_office_window
        """
        practice_a, practice_b, _, _ = two_practices_with_identical_office_hours
        world.set_clock("2026-08-01T14:30:00Z")
        call_a = world.open_call(
            practice_a["id"],
            caller_name="Saturday Caller A",
            caller_phone="+14155550101",
            reason_text="saturday, practice a",
        )
        world.set_clock("2026-08-03T22:00:00Z")
        at_close = world.open_call(
            practice_b["id"],
            caller_name="Monday Caller At Close",
            caller_phone="+14155550104",
            reason_text="exactly at the close minute",
        )

        assert world.call(call_a["id"])["status"] == "INTAKE"
        assert world.call(at_close["id"])["status"] == "INTAKE"
        assert world.call(call_a["id"])["is_after_hours"] is False, (
            "the frozen flag survives two clock advances"
        )

    def test_the_weekend_window_expires_lazily_while_the_nights_window_is_live(
        self, world, two_practices_with_identical_office_hours
    ):
        """PRD §3.2: "Whenever a coverage window is read individually, whenever a
        practice's windows are listed, and whenever an intake coverage check runs, any
        window whose `status` is `ACTIVE` and whose `end_utc` the logical clock has
        reached is first flipped to `EXPIRED`, bumping its `version`, and only then is
        the read or the check computed."

        Design: Corner/calculations/after_hours_flag_follows_the_practices_own_weekend_policy_and_the_half_open_office_window
        """
        _, practice_b, weekend, nights = two_practices_with_identical_office_hours
        world.set_clock("2026-08-03T22:00:00Z")
        world.open_call(
            practice_b["id"],
            caller_name="Monday Caller At Close",
            caller_phone="+14155550104",
            reason_text="exactly at the close minute",
        )

        assert world.coverage_window(weekend["id"])["status"] == "EXPIRED"
        assert world.coverage_window(nights["id"])["status"] == "ACTIVE"


@pytest.fixture
def licence_expiring_on_the_third(world):
    """One nurse, one CA licence, `expires_on` 2026-08-03."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_nurse("nurse_a")
    licence = world.add_license(
        "nurse_a", state_code="CA", license_number="CA-11111", expires_on="2026-08-03"
    )
    return licence


class TestLicenceStatusIsDerivedAtDayGranularity:
    def test_the_licence_is_active_all_through_its_expiry_date(
        self, world, licence_expiring_on_the_third
    ):
        """PRD §3.2: "a licence with `expires_on` of 2026-08-03 is `ACTIVE` at
        2026-08-03T23:59:00Z and `EXPIRED` at 2026-08-04T00:00:00Z."

        Design: Corner/calculations/license_status_is_active_through_the_expiry_date_and_expired_the_next_day
        """
        licence = licence_expiring_on_the_third
        assert licence["expires_on"] == "2026-08-03"

        midday, _ = validate_paginated(
            world.api.list_licenses(world.nurse_id("nurse_a"), world.admin)
        )
        world.set_clock("2026-08-03T23:59:59Z")
        last_second, _ = validate_paginated(
            world.api.list_licenses(world.nurse_id("nurse_a"), world.admin)
        )

        assert midday[0]["status"] == "ACTIVE"
        assert last_second[0]["status"] == "ACTIVE"

    def test_the_licence_flips_to_expired_at_the_next_midnight(
        self, world, licence_expiring_on_the_third
    ):
        """PRD §3.2: "A licence's `status` is never stored: it is computed at every
        read and at every eligibility evaluation as `ACTIVE` when `expires_on` is on
        or after the calendar date of the logical clock, and `EXPIRED` otherwise."

        Design: Corner/calculations/license_status_is_active_through_the_expiry_date_and_expired_the_next_day
        """
        assert licence_expiring_on_the_third["status"] == "ACTIVE"
        world.set_clock("2026-08-04T00:00:00Z")

        rows, _ = validate_paginated(
            world.api.list_licenses(world.nurse_id("nurse_a"), world.admin)
        )

        assert rows[0]["status"] == "EXPIRED"

    def test_the_status_filter_follows_the_derived_value(
        self, world, licence_expiring_on_the_third
    ):
        """PRD §3.2: "Licence listings may be narrowed by `state_code` and by
        `status`."

        Design: Corner/calculations/license_status_is_active_through_the_expiry_date_and_expired_the_next_day
        """
        assert licence_expiring_on_the_third["state_code"] == "CA"
        world.set_clock("2026-08-04T00:00:00Z")

        _, active_meta = validate_paginated(
            world.api.list_licenses(
                world.nurse_id("nurse_a"), world.admin, {"status": "ACTIVE"}
            )
        )
        expired_rows, expired_meta = validate_paginated(
            world.api.list_licenses(
                world.nurse_id("nurse_a"), world.admin, {"status": "EXPIRED"}
            )
        )

        assert active_meta["total_count"] == 0
        assert expired_meta["total_count"] == 1
        assert expired_rows[0]["expires_on"] == "2026-08-03"


@pytest.fixture
def day_shift_on_the_third(world):
    """One 2026-08-03T12:00Z-to-20:00Z shift, read by its own charge nurse."""
    world.set_clock("2026-08-03T14:30:00Z")
    world.create_nurse("nurse_a")
    shift = world.add_shift(
        "nurse_a", start_utc="2026-08-03T12:00:00Z", end_utc="2026-08-03T20:00:00Z"
    )
    return shift


class TestShiftStatusIsActiveOnlyOnItsHalfOpenInterval:
    def test_the_shift_is_scheduled_one_minute_before_it_starts(
        self, world, day_shift_on_the_third
    ):
        """PRD §3.2: "`SCHEDULED` while the clock is strictly before `start_utc`,
        `ACTIVE` while the clock is at or after `start_utc` and strictly before
        `end_utc`, and `ENDED` once the clock reaches `end_utc`."

        Design: Corner/calculations/shift_status_is_active_only_on_its_half_open_interval
        """
        shift = day_shift_on_the_third
        assert_whole_minutes(shift["scheduled_minutes"], 480, "scheduled_minutes")
        world.set_clock("2026-08-03T11:59:00Z")

        rows, _ = validate_paginated(
            world.api.list_shifts(
                world.nurse_id("nurse_a"), world.charge_headers("nurse_a")
            )
        )

        assert rows[0]["status"] == "SCHEDULED"

    def test_the_start_instant_is_inclusive_and_the_last_minute_is_still_active(
        self, world, day_shift_on_the_third
    ):
        """PRD §3.2: "The interval is half-open — the shift includes its start instant
        and excludes its end instant — which means one shift may begin at the exact
        instant another ends."

        Design: Corner/calculations/shift_status_is_active_only_on_its_half_open_interval
        """
        assert day_shift_on_the_third["status"] == "ACTIVE", "created inside its own span"
        world.set_clock("2026-08-03T12:00:00Z")
        at_start, _ = validate_paginated(
            world.api.list_shifts(
                world.nurse_id("nurse_a"), world.charge_headers("nurse_a")
            )
        )
        world.set_clock("2026-08-03T19:59:00Z")
        before_end, _ = validate_paginated(
            world.api.list_shifts(
                world.nurse_id("nurse_a"), world.charge_headers("nurse_a")
            )
        )

        assert at_start[0]["status"] == "ACTIVE"
        assert before_end[0]["status"] == "ACTIVE"

    def test_the_end_instant_is_exclusive_and_drops_out_of_the_active_filter(
        self, world, day_shift_on_the_third
    ):
        """PRD §3.2: "Shift listings may be narrowed by `status`."

        Design: Corner/calculations/shift_status_is_active_only_on_its_half_open_interval
        """
        shift = day_shift_on_the_third
        world.set_clock("2026-08-03T20:00:00Z")

        rows, _ = validate_paginated(
            world.api.list_shifts(
                world.nurse_id("nurse_a"), world.charge_headers("nurse_a")
            )
        )
        _, active_meta = validate_paginated(
            world.api.list_shifts(
                world.nurse_id("nurse_a"),
                world.charge_headers("nurse_a"),
                {"status": "ACTIVE"},
            )
        )

        assert rows[0]["status"] == "ENDED"
        assert active_meta["total_count"] == 0
        assert_whole_minutes(rows[0]["scheduled_minutes"], 480, "scheduled_minutes")


@pytest.fixture
def ed_now_advice_with_a_verified_callback(world):
    """An ED_NOW disposition (ordinal 4) whose HIGH_RISK callback is VERIFIED."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1
    )
    task = world.callback_for(disposition["id"])
    world.record_attempt(task["id"], "nurse_a", "REACHED")
    world.verify_callback(
        task["id"],
        "nurse_c",
        "IMPROVED",
        False,
        verifier_attestation=(
            "Caller chose their own physician office instead of the emergency "
            "department."
        ),
    )
    return assessment, disposition


class TestOvertriageScoresThreePointsPerOrdinal:
    def test_two_ordinal_steps_of_over_caution_are_worth_six_points(
        self, world, ed_now_advice_with_a_verified_callback
    ):
        """PRD §3.10: "`variance_severity_points` weights the gap asymmetrically,
        because under-triage is the dangerous direction: it is zero for a concordant
        record, seven points per ordinal step of divergence for an under-triage
        record, and three points per ordinal step for an over-triage record."

        Design: Corner/calculations/overtriage_outcome_scores_three_points_per_ordinal_and_never_escalates
        """
        assessment, disposition = ed_now_advice_with_a_verified_callback
        assert assessment["acuity_score"] == 70
        assert disposition["recommended_level"] == "ED_NOW"
        world.set_clock("2026-08-03T15:00:00Z")

        record = world.file_audit_record(
            disposition["id"],
            reported_outcome="OFFICE_VISIT",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T14:45:00Z",
        )

        assert record["variance_class"] == "OVERTRIAGE"
        assert record["variance_severity_points"] == 6
        assert record["outcome_ordinal"] == 2
        assert record["disposition_level_ordinal"] == 4

    def test_the_over_triage_record_escalates_nothing(
        self, world, ed_now_advice_with_a_verified_callback
    ):
        """PRD §3.10: "An `OVERTRIAGE` record does neither: it leaves the audit
        dimension resting at `OUTCOME_RECORDED`, escalates nothing, and touches no
        practice counter. Only under-triage escalates."

        Design: Corner/calculations/overtriage_outcome_scores_three_points_per_ordinal_and_never_escalates
        """
        _, disposition = ed_now_advice_with_a_verified_callback
        world.set_clock("2026-08-03T15:00:00Z")
        world.file_audit_record(
            disposition["id"],
            reported_outcome="OFFICE_VISIT",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T14:45:00Z",
        )

        after = world.disposition(disposition["id"])
        practice = world.practice()

        assert after["audit_status"] == "OUTCOME_RECORDED"
        assert after["advice_status"] == "AUTHORIZED"
        assert practice["open_variance_count"] == 0
        assert practice["compliance_posture"] == "NORMAL"

    def test_the_readout_counts_it_as_over_triage_and_concordant_by_neither_reading(
        self, world, ed_now_advice_with_a_verified_callback
    ):
        """PRD §3.10: "The clinical committee's band-tolerant reading counts a record
        as concordant when the two ordinals differ by at most one step in either
        direction, and reports that count as `concordant_count_band_tolerant`."

        Design: Corner/calculations/overtriage_outcome_scores_three_points_per_ordinal_and_never_escalates
        """
        _, disposition = ed_now_advice_with_a_verified_callback
        world.set_clock("2026-08-03T15:00:00Z")
        world.file_audit_record(
            disposition["id"],
            reported_outcome="OFFICE_VISIT",
            outcome_source="EHR_CLAIM",
            outcome_observed_at="2026-08-03T14:45:00Z",
        )
        world.set_clock("2026-08-03T15:01:00Z")

        summary = world.compliance_summary()

        assert summary["audited_count"] == 1
        assert_percentage(
            summary["concordance_rate_strict_pct"], 0.0, "concordance_rate_strict_pct"
        )
        assert_percentage(
            summary["concordance_rate_band_tolerant_pct"],
            0.0,
            "concordance_rate_band_tolerant_pct",
        )
        assert summary["overtriage_count"] == 1
        assert summary["undertriage_count"] == 0
        assert summary["variance_severity_points_total"] == 6
        assert summary["compliance_posture"] == "NORMAL"


@pytest.fixture
def saturday_night_home_care_advice(world):
    """After-hours HOME_CARE advice for a practice that opens at 13:00.

    The coverage window is drafted and activated before the clock reaches the
    weekend, and the nurse's shift straddles the Saturday-to-Sunday boundary so
    that the routing pool is not empty at 23:00.
    """
    world.bootstrap(
        clock="2026-07-30T12:00:00Z",
        nurse_keys=("nurse_a",),
        with_shifts=False,
        protocol={
            "code": "SORE_THROAT",
            "title": "Sore Throat Without Red Flags",
            "base_severity": 20,
            "min_disposition_level": "HOME_CARE",
        },
    )
    world.active_coverage(
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-03T00:00:00Z",
        coverage_kind="WEEKEND",
    )
    world.add_shift(
        "nurse_a", start_utc="2026-08-01T20:00:00Z", end_utc="2026-08-02T04:00:00Z"
    )
    world.set_clock("2026-08-01T23:00:00Z")
    call, assessment = world.call_through_assessment(
        "nurse_a", "protocol", red_flag_count=0, reason_text="sore throat, saturday night"
    )
    return call, assessment


class TestAfterHoursHomeCareOwesANextDayCallback:
    def test_after_hours_home_care_advice_still_owes_a_callback(
        self, world, saturday_night_home_care_advice
    ):
        """PRD §3.6: "`requires_callback` is true unless **both** of these hold: the
        `final_level` is `HOME_CARE` **and** the call's `is_after_hours` is false. In
        other words only in-hours home-care advice is exempt from a verification
        callback; after-hours home-care advice given on behalf of a closed practice
        always owes one, because there is no office to fall back on in the morning."

        Design: Corner/calculations/after_hours_home_care_advice_owes_a_next_day_callback_at_the_practices_opening_time
        """
        call, assessment = saturday_night_home_care_advice
        assert call["is_after_hours"] is True
        assert assessment["acuity_score"] == 20

        disposition = world.create_disposition(
            call["id"], assessment["id"], "HOME_CARE", "nurse_a"
        )

        assert disposition["recommended_level"] == "HOME_CARE"
        assert disposition["requires_callback"] is True

    def test_the_task_is_due_at_the_practices_opening_time_the_following_day(
        self, world, saturday_night_home_care_advice
    ):
        """PRD §3.6: "for a `NEXT_DAY` task the instant formed by taking the calendar
        date of `created_at`, adding one day, and applying the practice's
        `office_open_utc_hhmm` as the time of day — which is exactly why these tasks
        are called the practice's next-day callback list."

        Design: Corner/calculations/after_hours_home_care_advice_owes_a_next_day_callback_at_the_practices_opening_time
        """
        call, assessment = saturday_night_home_care_advice
        world.create_disposition(call["id"], assessment["id"], "HOME_CARE", "nurse_a")

        rows, meta = validate_paginated(
            world.api.list_callback_tasks(
                world.liaison_headers(),
                {"practice_id": world.practice_id, "risk_class": "NEXT_DAY"},
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["risk_class"] == "NEXT_DAY"
        assert_instant(rows[0]["due_by_utc"], "2026-08-02T13:00:00Z", "due_by_utc")
        assert rows[0]["max_attempts"] == 2, (
            "`max_attempts` is 3 for a HIGH_RISK task and 2 for every other class"
        )

    def test_the_fresh_task_is_pending_on_the_advising_nurses_list(
        self, world, saturday_night_home_care_advice
    ):
        """PRD §3.6: "exactly one callback task is created at `status` `PENDING`, with
        its `practice_id` copied from the call's practice and its `assigned_nurse_id`
        copied from the disposition's `determined_by_nurse_id`, and the practice's
        `open_callback_count` increases by one."

        Design: Corner/calculations/after_hours_home_care_advice_owes_a_next_day_callback_at_the_practices_opening_time
        """
        call, assessment = saturday_night_home_care_advice
        disposition = world.create_disposition(
            call["id"], assessment["id"], "HOME_CARE", "nurse_a"
        )

        task = world.callback_for(disposition["id"])

        assert task["status"] == "PENDING"
        assert task["assigned_nurse_id"] == world.nurse_id("nurse_a")
        assert task["practice_id"] == world.practice_id
        assert task["attempt_count"] == 0
        assert world.practice()["open_callback_count"] == 1
        assert world.call(call["id"])["requires_warm_transfer"] is False
