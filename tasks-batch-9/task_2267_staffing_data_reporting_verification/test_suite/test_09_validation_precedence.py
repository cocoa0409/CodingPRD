"""Which single error wins when one hour write violates two rules at once."""

from test_helpers import (
    ApiErrorId,
    SubmissionStatus,
    TEST_DEFAULTS,
    approx_hours,
    create_hour_entry_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOSED_WINDOW_CLOCK = "2027-01-05T00:00:00Z"


class TestSubmissionStateBeatsCorrectionWindow:
    def test_01_the_submission_state_error_wins_over_the_closed_window(
        self, api, accepted_quarter
    ):
        """PRD: "The target `QuarterlySubmission` is in a status the requested
        operation accepts — otherwise `ERR_SUBMISSION_STATE_INVALID`. Hour writes
        and census writes accept `DRAFT` or `VALIDATED`" is check 18, while "The
        logical clock is at or before the submission's `correction_deadline` —
        otherwise `ERR_CORRECTION_WINDOW_CLOSED`" is check 42, and "Checks are
        evaluated in the following order, and the first violation encountered
        wins."

        Design: Difficulty/priority_pair_validation_conflict/submission_state_error_precedes_correction_window_error
        """
        scenario = accepted_quarter
        universe = scenario.universe
        version = scenario.version
        universe.set_clock(CLOSED_WINDOW_CLOCK)

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                version,
                work_date="2026-04-02",
                shift_start="07:00",
                shift_end="15:00",
            ),
            universe.coord_headers,
        )

        validate_error(response, ApiErrorId.ERR_SUBMISSION_STATE_INVALID.value)

    def test_02_the_refused_write_leaves_the_quarter_untouched(
        self, api, accepted_quarter
    ):
        """PRD: "Operations that bring a new resource into existence — every
        `POST` that creates a row — return `201 Created`." A refused creation
        brings nothing into existence, so the accepted quarter keeps its rollups
        and its `version`.

        Design: Difficulty/priority_pair_validation_conflict/submission_state_error_precedes_correction_window_error
        """
        scenario = accepted_quarter
        universe = scenario.universe
        before = scenario.refresh()
        universe.set_clock(CLOSED_WINDOW_CLOCK)

        api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                before["version"],
                work_date="2026-04-02",
                shift_start="07:00",
                shift_end="15:00",
            ),
            universe.coord_headers,
        )

        after = scenario.refresh()
        assert after["status"] == SubmissionStatus.ACCEPTED.value
        assert after["total_direct_care_hours"] == approx_hours(8.00)
        assert after["version"] == before["version"]

        entries, _ = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {"submission_id": scenario.id, "limit": 100},
            )
        )
        assert len(entries) == 1


class TestWorkerFacilityMismatchBeatsShiftLength:
    def test_01_the_worker_facility_mismatch_wins_over_the_shift_length_cap(
        self, api, draft_submission
    ):
        """PRD: "On hour creation and on agency batch acceptance, the referenced
        `Worker`'s `facility_id` equals the target submission's `facility_id` —
        otherwise `ERR_WORKER_FACILITY_MISMATCH`" is check 44, while "On hour
        creation and on agency batch acceptance, the computed shift length does not
        exceed the maximum single-shift length — otherwise
        `ERR_SHIFT_LENGTH_EXCEEDED`" is check 50, and "the first violation
        encountered wins."

        Design: Difficulty/priority_pair_validation_conflict/worker_facility_mismatch_precedes_shift_length_error
        """
        scenario = draft_submission
        universe = scenario.universe
        other_facility = universe.register_facility(
            ccn=TEST_DEFAULTS["SECOND_FACILITY_CCN"],
            name=TEST_DEFAULTS["SECOND_FACILITY_NAME"],
            certified_bed_count=TEST_DEFAULTS["SECOND_FACILITY_BED_COUNT"],
        )
        outsider = universe.register_worker(
            other_facility["id"],
            universe.jc_rn["id"],
            full_name="Sam Substitute",
            authorized_roles=[],
        )

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                outsider["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-01",
                shift_start="06:00",
                shift_end="23:00",
            ),
            universe.coord_headers,
        )

        validate_error(response, ApiErrorId.ERR_WORKER_FACILITY_MISMATCH.value)

    def test_02_no_hour_row_and_no_derived_total_move(self, api, draft_submission):
        """PRD: "`reported_hours_total` is refreshed for every worker referenced by
        the active hour population". A refused creation adds no member to that
        population, so the outsider's total stays at its registration value and the
        quarter's `version` does not advance.

        Design: Difficulty/priority_pair_validation_conflict/worker_facility_mismatch_precedes_shift_length_error
        """
        scenario = draft_submission
        universe = scenario.universe
        other_facility = universe.register_facility(
            ccn=TEST_DEFAULTS["SECOND_FACILITY_CCN"],
            name=TEST_DEFAULTS["SECOND_FACILITY_NAME"],
            certified_bed_count=TEST_DEFAULTS["SECOND_FACILITY_BED_COUNT"],
        )
        outsider = universe.register_worker(
            other_facility["id"],
            universe.jc_rn["id"],
            full_name="Sam Substitute",
            authorized_roles=[],
        )
        version_before = scenario.version

        api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                outsider["id"],
                universe.jc_rn["id"],
                version_before,
                work_date="2026-04-01",
                shift_start="06:00",
                shift_end="23:00",
            ),
            universe.coord_headers,
        )

        entries, _ = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {"submission_id": scenario.id, "limit": 100},
            )
        )
        assert entries == []
        assert scenario.refresh()["version"] == version_before

        worker = validate_success(
            api.get_worker(outsider["id"], universe.coord_headers)
        )
        assert worker["reported_hours_total"] == approx_hours(0.00)
