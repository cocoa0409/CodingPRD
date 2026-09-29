"""The submission cycle re-entering VALIDATED after an amendment."""

from test_helpers import (
    SubmissionStatus,
    approx_hours,
    approx_ratio,
    validate_success,
)


class TestSubmissionCycleReopenAndRevalidate:
    def test_01_a_reopened_quarter_can_be_validated_a_second_time(
        self, api, accepted_quarter
    ):
        """PRD: "**Validation** is the staffing office's dry run of the quarter,
        and it is re-runnable: every run recomputes findings from scratch. It
        requires the submission to be in `DRAFT`" and it "moves `status` from
        `DRAFT` to `VALIDATED`". Reopening "lands the submission back in `DRAFT`,
        closing the cycle `DRAFT → VALIDATED → SUBMITTED → ACCEPTED → DRAFT`", so
        the same submission re-enters `VALIDATED` on the second pass.

        Design: Difficulty/non_linear_state_machine/submission_cycle_accepted_reopened_revalidated
        """
        scenario = accepted_quarter
        reopened = validate_success(
            api.reopen_submission(scenario.id, scenario.universe.coord_headers)
        )
        assert reopened["status"] == SubmissionStatus.DRAFT.value

        data = validate_success(
            api.validate_submission(scenario.id, scenario.universe.coord_headers)
        )

        assert data["status"] == SubmissionStatus.VALIDATED.value
        assert data["amendment_index"] == 1

    def test_02_revalidation_reestablishes_the_validator_but_not_the_attestor(
        self, api, accepted_quarter
    ):
        """PRD: reopening "clears both `validated_by_worker_id` and
        `attested_by_worker_id` so the segregation-of-duties pairing must be
        re-established". PRD: a successful validation run "records the acting
        worker's id as `validated_by_worker_id`".

        Design: Difficulty/non_linear_state_machine/submission_cycle_accepted_reopened_revalidated
        """
        scenario = accepted_quarter
        universe = scenario.universe
        validate_success(api.reopen_submission(scenario.id, universe.coord_headers))

        data = validate_success(
            api.validate_submission(scenario.id, universe.coord_headers)
        )

        assert data["validated_by_worker_id"] == universe.w_coord["id"]
        assert data["attested_by_worker_id"] is None

    def test_03_the_amendment_is_free_of_late_fees_before_the_deadline(
        self, api, accepted_quarter
    ):
        """PRD: "lateness is measured from the period's `submission_deadline`:
        take the whole seconds from that deadline to the current logical clock
        instant; if that is zero or negative there are no late days". PRD: the
        base fee "otherwise is 25000 cents plus 2500 cents for each amendment
        beyond the first". The clock still reads its initial instant, which
        precedes the deadline, so the first amendment costs exactly the base fee.

        Design: Difficulty/non_linear_state_machine/submission_cycle_accepted_reopened_revalidated
        """
        scenario = accepted_quarter
        universe = scenario.universe
        validate_success(api.reopen_submission(scenario.id, universe.coord_headers))
        data = validate_success(
            api.validate_submission(scenario.id, universe.coord_headers)
        )

        assert data["amendment_surcharge_cents"] == 25000
        assert data["waived_surcharge_cents"] == 0

    def test_04_revalidation_recomputes_the_rollups_and_the_reported_metric(
        self, api, accepted_quarter
    ):
        """PRD: "A successful run refreshes every hour and census rollup, computes
        the as-submitted hours per resident day into `hprd_reported` and the
        weekend figure into `weekend_hprd_reported`, rebuilds the finding set,
        refreshes `open_fatal_finding_count` and `open_warning_finding_count`".
        The stored quarter still holds one 8.00-hour supported RN shift over a
        single reconciled census day counting 5 residents.

        Design: Difficulty/non_linear_state_machine/submission_cycle_accepted_reopened_revalidated
        """
        scenario = accepted_quarter
        universe = scenario.universe
        validate_success(api.reopen_submission(scenario.id, universe.coord_headers))

        data = validate_success(
            api.validate_submission(scenario.id, universe.coord_headers)
        )

        assert data["total_direct_care_hours"] == approx_hours(8.00)
        assert data["total_resident_days"] == 5
        assert data["hprd_reported"] == approx_ratio(1.6000)
        assert data["open_fatal_finding_count"] == 0
