"""Validation-ladder sequences.

Three shapes of ladder behaviour: the all-or-nothing headcount batch writer, the
satisfaction side of the prior-year headcount guard on the applicable-large-employer
determination, and the cascade from the measurement-cycle rung down to the
look-back denominator rung on the employee full-time recompute.
"""

import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    assert_controlled_group,
    factories,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

CO = TEST_USERS["compliance_officer"]
BA = TEST_USERS["benefits_admin"]
PREPARER = TEST_USERS["preparer"]


# ---------------------------------------------------------------------------
# World builders (compositions of test_helpers.fixtures)
# ---------------------------------------------------------------------------
def _member_with_twelve_prior_year_months(api):
    """Season -> controlled group -> one member -> twelve PRIOR_YEAR headcount
    months, posted as two batches so a retry of the whole year collides on a
    single month only."""
    season = fixtures.create_filing_season(api, CO)
    group = fixtures.create_controlled_group(api, season["id"], CO)
    member = fixtures.create_group_member(
        api, group["id"], headers=CO, measurement_method="MONTHLY"
    )
    fixtures.record_headcounts(api, member["id"], months=[12], headers=CO)
    fixtures.record_headcounts(api, member["id"], months=list(range(1, 12)), headers=CO)
    return season, group, member


def _prior_year_headcounts(api, member_id):
    return validate_paginated(
        api.list_monthly_headcounts(
            CO,
            params={
                "group_member_id": member_id,
                "count_year": "PRIOR_YEAR",
                "limit": 100,
            },
        )
    )


def _two_member_group_with_complete_headcounts(api):
    """Two ACTIVE members, each carrying all twelve PRIOR_YEAR months, with the
    determination deliberately not yet run."""
    season = fixtures.create_filing_season(api, CO)
    group = fixtures.create_controlled_group(api, season["id"], CO)
    member_a = fixtures.create_group_member(
        api,
        group["id"],
        ein="888888881",
        headers=CO,
        legal_name="Ironwood Main",
        ownership_pct=70,
        measurement_method="MONTHLY",
    )
    member_b = fixtures.create_group_member(
        api,
        group["id"],
        ein="888888882",
        headers=CO,
        legal_name="Ironwood Annex",
        ownership_pct=30,
        measurement_method="MONTHLY",
    )
    fixtures.record_headcounts(
        api,
        member_a["id"],
        headers=CO,
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    fixtures.record_headcounts(
        api,
        member_b["id"],
        headers=CO,
        full_time_employee_count=20,
        part_time_hours_total=0,
        total_employee_count=22,
    )
    return season, group, member_a, member_b


def _run_determination(api, group_id):
    version = fixtures.current_group_version(api, group_id, CO)
    return api.run_ale_determination(
        group_id, factories.ale_determination_payload(version, basis="AGGREGATED"), CO
    )


def _look_back_variable_hour_employee(api):
    """A LOOK_BACK member with a determined-ALE group and one VARIABLE_HOUR
    employee that inherits the method, with no measurement cycle and no hours."""
    return fixtures.determined_ale_group_with_employee(
        api,
        member_measurement_method="LOOK_BACK",
        employee_overrides={
            "full_name": "Rosa Klein",
            "ssn_last4": "6060",
            "employment_type": "VARIABLE_HOUR",
            "is_hourly": True,
            "hourly_rate_cents": 1500,
        },
    )


# ---------------------------------------------------------------------------
# Atomic batch writes on the headcount collection
# ---------------------------------------------------------------------------
class TestHeadcountBatchAtomicity:
    def test_headcount_batch_colliding_on_one_month_is_rejected(self, api):
        """PRD §2.6: "No headcount row already exists for any requested
        member-year-month triple — `ERR_DUPLICATE_HEADCOUNT_MONTH` (409), on
        headcount creation."
        PRD §2.11: "Recording headcounts creates one row per entry of the `months`
        array, all carrying the same counts; if any one of those member-year-month
        triples already exists, the entire call is rejected and nothing is created."

        Design: Corner/Validations/duplicate_headcount_month_batch_is_atomic
        """
        _, _, member = _member_with_twelve_prior_year_months(api)

        response = api.create_monthly_headcounts(
            factories.monthly_headcounts_payload(
                member["id"],
                list(range(1, 13)),
                count_year="PRIOR_YEAR",
                full_time_employee_count=41,
                part_time_hours_total=0,
                total_employee_count=61,
            ),
            BA,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_HEADCOUNT_MONTH, 409)

    def test_rejected_headcount_batch_writes_none_of_its_eleven_free_months(self, api):
        """PRD §2.11: "Recording headcounts creates one row per entry of the `months`
        array, all carrying the same counts; if any one of those member-year-month
        triples already exists, the entire call is rejected and nothing is created."
        PRD §2.11: "Partial application is never acceptable in any of the three."

        Design: Corner/Validations/duplicate_headcount_month_batch_is_atomic
        """
        _, _, member = _member_with_twelve_prior_year_months(api)

        api.create_monthly_headcounts(
            factories.monthly_headcounts_payload(
                member["id"],
                list(range(1, 13)),
                count_year="PRIOR_YEAR",
                full_time_employee_count=41,
                part_time_hours_total=0,
                total_employee_count=61,
            ),
            BA,
        )

        rows, meta = _prior_year_headcounts(api, member["id"])
        assert meta["total_count"] == 12, (
            "the rejected twelve-month batch must leave exactly the twelve "
            f"pre-existing rows, got total_count {meta['total_count']}"
        )
        assert sorted(row["month"] for row in rows) == list(range(1, 13))
        for row in rows:
            assert row["full_time_employee_count"] == 40, (
                f"month {row['month']} carries the rejected batch's count"
            )
            assert row["part_time_hours_total"] == 1200
            assert float(row["member_fte"]) == pytest.approx(50.00, abs=0.01), (
                f"month {row['month']} member_fte should still be 40 + 1200/120"
            )

    def test_headcount_uniqueness_key_includes_the_count_year(self, api):
        """PRD §2.6: "No headcount row already exists for any requested
        member-year-month triple — `ERR_DUPLICATE_HEADCOUNT_MONTH` (409), on
        headcount creation."
        PRD §3.1: "Each batch names a `count_year` — `PRIOR_YEAR` rows describe the
        calendar year one before the season's `tax_year` and are the only input to
        the applicable-large-employer determination, while `REPORTING_YEAR` rows
        describe the reporting year itself and feed the 1094-C Part III counts and
        the penalty arithmetic."

        Design: Corner/Validations/duplicate_headcount_month_batch_is_atomic
        """
        _, _, member = _member_with_twelve_prior_year_months(api)

        response = api.create_monthly_headcounts(
            factories.monthly_headcounts_payload(
                member["id"],
                list(range(1, 13)),
                count_year="REPORTING_YEAR",
                full_time_employee_count=41,
                part_time_hours_total=0,
                total_employee_count=61,
            ),
            BA,
        )

        created = validate_success(response, 201)
        assert len(created) == 12, (
            "the same twelve months under REPORTING_YEAR are a different triple "
            f"and must all be created, got {len(created)} rows"
        )
        _, prior_year_meta = _prior_year_headcounts(api, member["id"])
        assert prior_year_meta["total_count"] == 12


# ---------------------------------------------------------------------------
# The satisfaction path of the prior-year headcount guard
# ---------------------------------------------------------------------------
class TestCompleteHeadcountsDetermination:
    def test_determination_passes_with_twelve_months_for_every_counted_member(self, api):
        """PRD §2.6: "Twelve prior-year headcount months exist for every counted
        member — `ERR_HEADCOUNT_INCOMPLETE` (409), on ale-determination."
        PRD §3.2: "Under the aggregated basis the counted set is every `ACTIVE`
        member of the group; under the single-member basis it is exactly the named
        member."

        Design: Corner/Validations/complete_headcounts_and_determination_pass
        """
        _, group, _, _ = _two_member_group_with_complete_headcounts(api)

        response = _run_determination(api, group["id"])

        determined = validate_success(response, 200)
        assert_controlled_group(
            determined,
            determination_state="DETERMINED_ALE",
            determination_basis="AGGREGATED",
            single_member_id=None,
        )

    def test_aggregated_monthly_group_fte_sums_members_before_truncating(self, api):
        """PRD §3.2: "Those per-member values are added together at full two-decimal
        precision, the sum itself is rounded half up to two decimal places, and only
        then is the month's group figure truncated to a whole number and stored in
        `monthly_group_fte`, whose first element is January of the prior year."
        PRD §3.2: "The twelve stored monthly figures are then summed, divided by 12,
        and rounded half up to two decimal places to give `annual_average_fte_raw`;
        truncating that value gives the whole-number `annual_average_fte` that is
        compared against the threshold of 50 full-time-equivalent employees."

        Design: Corner/Validations/complete_headcounts_and_determination_pass
        """
        _, group, _, _ = _two_member_group_with_complete_headcounts(api)

        determined = validate_success(_run_determination(api, group["id"]), 200)

        assert determined["monthly_group_fte"] == [70] * 12, (
            "each month is member A's 50.00 plus member B's 20.00, truncated after "
            f"the sum, got {determined['monthly_group_fte']}"
        )
        assert float(determined["annual_average_fte_raw"]) == pytest.approx(70.00, abs=0.01)
        assert determined["annual_average_fte"] == 70

    def test_determination_above_threshold_reports_threshold_met(self, api):
        """PRD §3.2: "When `annual_average_fte` is at least 50 but that exception
        does not apply, the group becomes `DETERMINED_ALE` with `ale_reason` of
        `THRESHOLD_MET` and `seasonal_exception_applied` false."
        PRD §3.2: "First, the number of months whose stored group figure is
        **strictly greater** than 50 must be at most four."

        Design: Corner/Validations/complete_headcounts_and_determination_pass
        """
        _, group, _, _ = _two_member_group_with_complete_headcounts(api)

        determined = validate_success(_run_determination(api, group["id"]), 200)

        assert determined["ale_reason"] == "THRESHOLD_MET"
        assert determined["seasonal_exception_applied"] is False

    def test_determination_stamps_actor_and_advances_group_version(self, api):
        """PRD §3.2: "Whichever branch fires, the determination writes
        `monthly_group_fte`, `annual_average_fte_raw`, `annual_average_fte`,
        `determination_basis` (`AGGREGATED` or `SINGLE_MEMBER`), `ale_reason` and
        `seasonal_exception_applied`, stamps `determined_at` from the logical clock
        and `last_determination_user_id` from the acting officer, and increments the
        group's `version` by one."

        Design: Corner/Validations/complete_headcounts_and_determination_pass
        """
        _, group, _, _ = _two_member_group_with_complete_headcounts(api)

        determined = validate_success(_run_determination(api, group["id"]), 200)

        assert determined["determined_at"] is not None, "determined_at must be stamped"
        assert is_iso8601_timestamp(determined["determined_at"])
        assert determined["last_determination_user_id"] == COMPLIANCE_OFFICER_USER_ID
        assert determined["version"] == 2, (
            f"a fresh group is version 1; the determination must advance it to 2, "
            f"got {determined['version']}"
        )


# ---------------------------------------------------------------------------
# The measurement-cycle rung cascading into the look-back denominator rung
# ---------------------------------------------------------------------------
class TestLookBackRecomputeCascade:
    def test_recompute_without_cycle_and_without_hours_reports_measurement_conflict(self, api):
        """PRD §2.6: "Every mutating endpoint runs one shared ladder from the top and
        returns the **first** rule it violates; lower numbers win."
        PRD §2.6: "A look-back employee has a governing measurement cycle —
        `ERR_MEASUREMENT_METHOD_CONFLICT` (409), on the employee full-time recompute,
        form generation and regenerate."
        PRD §3.5: "The governing cycle is the employee's own `INITIAL` cycle when one
        exists, and otherwise the `STANDARD` cycle of the employee's member; when
        neither exists the recompute is refused with
        `ERR_MEASUREMENT_METHOD_CONFLICT`."

        Design: Corner/Validations/cascading_measurement_conflict_before_hours_check
        """
        ctx = _look_back_variable_hour_employee(api)
        employee = ctx["employee"]
        assert employee["effective_measurement_method"] == "LOOK_BACK", (
            "the employee sets no override, so it inherits the member's method"
        )

        response = api.recompute_employee_full_time(employee["id"], PREPARER)

        validate_error(response, ApiErrorId.ERR_MEASUREMENT_METHOD_CONFLICT, 409)

    def test_refused_recompute_leaves_the_look_back_outputs_untouched(self, api):
        """PRD §3.3: "A new hire starts `ACTIVE` with a null `termination_date`, a
        null `open_leave_type`, `full_time_month_count` of 0, empty
        `full_time_months`, a null `measured_average_hours` and a null
        `last_recomputed_at`."
        PRD §3.5: "The recompute writes `full_time_months`, `full_time_month_count`,
        `measured_average_hours`, `ft_source_by_month` and `last_recomputed_at` on
        the employee, and refreshes `full_time_flag`, `ft_source` and `assessable` on
        the coverage lines of the employee's non-voided statement."

        Design: Corner/Validations/cascading_measurement_conflict_before_hours_check
        """
        ctx = _look_back_variable_hour_employee(api)
        employee = ctx["employee"]

        api.recompute_employee_full_time(employee["id"], PREPARER)

        after = fixtures.read_employee(api, employee["id"])
        assert after["measured_average_hours"] is None, (
            "a refused recompute must not write measured_average_hours"
        )
        assert after["last_recomputed_at"] is None, (
            "a refused recompute must not stamp last_recomputed_at"
        )
        assert after["full_time_month_count"] == 0
        assert after["full_time_months"] == []

    def test_standard_cycle_defaults_the_monthly_hours_threshold(self, api):
        """PRD §3.3: "`hours_threshold_monthly` defaults to 130 and is the monthly
        average at or above which the employee is full time for the whole stability
        period."

        Design: Corner/Validations/cascading_measurement_conflict_before_hours_check
        """
        ctx = _look_back_variable_hour_employee(api)

        response = api.create_measurement_cycle(
            factories.measurement_cycle_payload(
                ctx["member"]["id"],
                cycle_type="STANDARD",
                measurement_start_date="2025-01-01",
                measurement_end_date="2025-12-31",
                admin_period_end_date="2025-12-31",
                stability_start_date="2026-01-01",
                stability_end_date="2026-12-31",
            ),
            CO,
        )

        cycle = validate_success(response, 201)
        assert cycle["hours_threshold_monthly"] == 130

    def test_recompute_with_cycle_but_no_hours_rows_reports_no_hours_data(self, api):
        """PRD §2.6: "The look-back denominator is non-empty — `ERR_NO_HOURS_DATA`
        (422), on the employee full-time recompute, form generation and regenerate."
        PRD §3.5: "The measurement months are those months whose first day falls
        within the cycle's measurement start and end dates inclusive, and the input
        set is the employee's hours rows for those months whose
        `excluded_from_denominator` is false. If that filtered set is empty the
        recompute is refused with `ERR_NO_HOURS_DATA`."

        Design: Corner/Validations/cascading_measurement_conflict_before_hours_check
        """
        ctx = _look_back_variable_hour_employee(api)
        employee = ctx["employee"]
        fixtures.create_measurement_cycle(
            api,
            ctx["member"]["id"],
            headers=CO,
            cycle_type="STANDARD",
            measurement_start_date="2025-01-01",
            measurement_end_date="2025-12-31",
            admin_period_end_date="2025-12-31",
            stability_start_date="2026-01-01",
            stability_end_date="2026-12-31",
        )

        response = api.recompute_employee_full_time(employee["id"], PREPARER)

        validate_error(response, ApiErrorId.ERR_NO_HOURS_DATA, 422)
        after = fixtures.read_employee(api, employee["id"])
        assert after["effective_measurement_method"] == "LOOK_BACK", (
            "the member's method is inherited, never rewritten by a refused recompute"
        )
