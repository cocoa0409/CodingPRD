"""The error catalogue exercised where each code is the only possible answer:
lookup failures, header failures, and shape failures."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SubmissionStatus,
    UserRole,
    assert_envelope_meta,
    build_user_headers,
    create_census_day_payload,
    create_hour_entry_payload,
    validate_error,
    validate_paginated,
)


class TestEntitySpecificNotFound:
    def test_01_each_read_answers_with_its_own_entitys_not_found_code(
        self, api, platform_admin_headers
    ):
        """PRD: "each entity has its own not-found code: `ERR_FACILITY_NOT_FOUND`,
        `ERR_REPORTING_PERIOD_NOT_FOUND`, `ERR_JOB_CATEGORY_NOT_FOUND`,
        `ERR_WORKER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
        `ERR_VENDOR_SUBMISSION_NOT_FOUND`, `ERR_PAYROLL_RECORD_NOT_FOUND`,
        `ERR_HOUR_ENTRY_NOT_FOUND`, `ERR_CENSUS_DAY_NOT_FOUND`,
        `ERR_SUBMISSION_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`,
        `ERR_CASE_NOT_FOUND`, and `ERR_APPEAL_NOT_FOUND`." PRD: "Every identifier in the
        request path resolves, left to right — otherwise the corresponding not-found code
        from §2.10."

        Design: Corner/errors/unknown_ids_return_the_entity_specific_not_found_error
        """
        probes = [
            (api.get_facility, ApiErrorId.ERR_FACILITY_NOT_FOUND),
            (api.get_reporting_period, ApiErrorId.ERR_REPORTING_PERIOD_NOT_FOUND),
            (api.get_job_category, ApiErrorId.ERR_JOB_CATEGORY_NOT_FOUND),
            (api.get_worker, ApiErrorId.ERR_WORKER_NOT_FOUND),
            (api.get_vendor, ApiErrorId.ERR_VENDOR_NOT_FOUND),
            (api.get_vendor_submission, ApiErrorId.ERR_VENDOR_SUBMISSION_NOT_FOUND),
            (api.get_payroll_record, ApiErrorId.ERR_PAYROLL_RECORD_NOT_FOUND),
            (api.get_hour_entry, ApiErrorId.ERR_HOUR_ENTRY_NOT_FOUND),
            (api.get_census_day, ApiErrorId.ERR_CENSUS_DAY_NOT_FOUND),
            (api.get_submission, ApiErrorId.ERR_SUBMISSION_NOT_FOUND),
            (api.get_validation_finding, ApiErrorId.ERR_FINDING_NOT_FOUND),
            (api.get_staffing_measure, ApiErrorId.ERR_MEASURE_NOT_FOUND),
            (api.get_discrepancy_case, ApiErrorId.ERR_CASE_NOT_FOUND),
            (api.get_rating_appeal, ApiErrorId.ERR_APPEAL_NOT_FOUND),
        ]

        for read, expected in probes:
            response = read(NON_EXISTENT_UUID, platform_admin_headers)
            validate_error(response, expected.value, expected_status=404)
            body = response.json()
            assert body["response_type"] == "error"
            assert_envelope_meta(body)
            assert body["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


class TestHeaderAndIdentityProbes:
    def test_01_the_three_header_failures_are_reported_separately(
        self, api, draft_submission
    ):
        """PRD: "Every request to the API — reads included — must carry two headers:
        `X-User-ID`, naming the acting identity, and `X-User-Role`, naming the capacity
        that identity is acting in. If either header is absent or empty, the request is
        rejected with `ERR_UNAUTHENTICATED`. If `X-User-Role` carries a string that is not
        one of the seven role names below, the request is rejected with
        `ERR_UNKNOWN_ROLE`." PRD: "For the three entity-backed roles, an `X-User-ID` that
        does not resolve to an existing row of the backing entity is rejected with
        `ERR_IDENTITY_NOT_FOUND`."

        Design: Corner/errors/authentication_and_identity_header_probes_rejected
        """
        scenario = draft_submission
        universe = scenario.universe

        role_less = api.get_facility(
            universe.facility_id,
            {"X-User-ID": "admin-01", "Content-Type": "application/json"},
        )
        validate_error(role_less, ApiErrorId.ERR_UNAUTHENTICATED.value)

        unknown_role = api.get_facility(
            universe.facility_id, build_user_headers("admin-01", "RegionalDirector")
        )
        validate_error(unknown_role, ApiErrorId.ERR_UNKNOWN_ROLE.value)

        unresolvable = api.validate_submission(
            scenario.id,
            build_user_headers(
                NON_EXISTENT_UUID, UserRole.STAFFING_COORDINATOR.value
            ),
        )
        validate_error(unresolvable, ApiErrorId.ERR_IDENTITY_NOT_FOUND.value)

        assert scenario.refresh()["status"] == SubmissionStatus.DRAFT.value


class TestPaginationAndDateShape:
    def test_01_out_of_bounds_windows_and_malformed_dates_are_refused(
        self, api, draft_submission
    ):
        """PRD: "`limit` caps the number of rows returned; it defaults to 10, has a
        minimum of 1 and a maximum of 100. `offset` is the number of rows to skip and
        defaults to 0, with no upper bound. A `limit` that is not an integer in the range
        1 through 100 inclusive, or an `offset` that is not an integer of zero or greater,
        is rejected with `ERR_INVALID_PAGINATION`." PRD: "Date fields match the
        `YYYY-MM-DD` shape, time-of-day fields match `HH:MM` in 24-hour form, and datetime
        fields are ISO 8601 UTC — otherwise `ERR_INVALID_DATE_FORMAT`."

        Design: Corner/errors/pagination_and_date_shape_probes_rejected
        """
        scenario = draft_submission
        universe = scenario.universe

        over_limit = api.list_submissions(
            universe.coord_headers,
            {"facility_id": universe.facility_id, "limit": 101, "offset": 0},
        )
        validate_error(over_limit, ApiErrorId.ERR_INVALID_PAGINATION.value)

        negative_offset = api.list_submissions(
            universe.coord_headers,
            {"facility_id": universe.facility_id, "limit": 10, "offset": -1},
        )
        validate_error(negative_offset, ApiErrorId.ERR_INVALID_PAGINATION.value)

        slashed_date = api.create_census_day(
            create_census_day_payload(
                scenario.id, census_date="04/15/2026", resident_count=6
            ),
            universe.coord_headers,
        )
        validate_error(slashed_date, ApiErrorId.ERR_INVALID_DATE_FORMAT.value)

        impossible_date = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-31",
                shift_start="7:00",
            ),
            universe.coord_headers,
        )
        validate_error(impossible_date, ApiErrorId.ERR_INVALID_DATE_FORMAT.value)

        _, census_meta = validate_paginated(
            api.list_census_days(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert census_meta["total_count"] == 0
        _, hour_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert hour_meta["total_count"] == 0
        assert scenario.refresh()["version"] == 1
