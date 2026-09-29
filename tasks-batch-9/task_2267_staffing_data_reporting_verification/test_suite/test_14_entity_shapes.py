"""Entity payload shapes: creation, retrieval, listing, defaults, and the
foreign-key resolution that guards both."""

from test_helpers import (
    ApiErrorId,
    CensusDayStatus,
    EntryStatus,
    FacilityPosture,
    SubmissionStatus,
    TEST_DEFAULTS,
    VerificationStatus,
    WorkerStatus,
    allocation_line,
    approx_hours,
    approx_score,
    assert_envelope_meta,
    assert_facility,
    assert_instant_equals,
    assert_payroll_record,
    create_facility_payload,
    create_hour_entry_payload,
    create_job_category_payload,
    create_worker_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_CENSUS_DAY_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_SUBMISSION_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_JOB_CATEGORY_ID = "33333333-3333-4333-8333-333333333333"
CLAIMED_FACILITY_ID = "11111111-1111-4111-8111-111111111111"


class TestHourEntryCreation:
    def test_01_capturing_a_shift_returns_201_with_the_full_classification(
        self, api, draft_submission
    ):
        """PRD: "Operations that bring a new resource into existence — ... capturing
        an hour entry, ... — return `201 Created`." PRD: "its `entry_status` starts at
        `ACTIVE`, its `verification_status` starts at `UNVERIFIED`, its
        `verified_by_user_id` starts at null, and its `allocation_revision` starts at
        0. The `version` of the parent submission is incremented and that new value is
        recorded on the entry as `submission_version`."

        Design: Corner/entities/hour_entry_creation_returns_classification_fields_and_success_envelope
        """
        scenario = draft_submission
        universe = scenario.universe

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
            ),
            universe.coord_headers,
        )
        data = validate_success(response, expected_status=201)

        body = response.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "object"

        assert is_valid_uuid(data["id"])
        assert data["raw_hours"] == approx_hours(8.00)
        assert data["direct_care_hours"] == approx_hours(8.00)
        assert data["excluded_hours"] == approx_hours(0.00)
        assert data["rn_hours"] == approx_hours(8.00)
        assert data["entry_status"] == EntryStatus.ACTIVE.value
        assert data["verification_status"] == VerificationStatus.UNVERIFIED.value
        assert data["verified_by_user_id"] is None
        assert data["is_weekend"] is False
        assert data["allocation_revision"] == 0
        assert data["version"] == 1
        assert data["submission_version"] == 2


class TestSubmissionRetrieval:
    def test_01_the_stored_submission_reflects_the_hour_and_census_writes(
        self, api, supported_quarter
    ):
        """PRD: "`total_raw_hours` is the sum of `raw_hours`, `total_direct_care_hours`
        the sum of `direct_care_hours`, `total_excluded_hours` the sum of
        `excluded_hours`, and `total_rn_direct_care_hours` the sum of `rn_hours`, each
        rounded half up to 2 decimal places." PRD: on creation the submission "sets
        `amendment_index` to 0, sets every hour and money rollup to its zero value ...
        and copies the period's `correction_window_end` into `correction_deadline`."

        Design: Corner/entities/submission_retrieval_reflects_rollup_from_hour_and_census_writes
        """
        scenario = supported_quarter
        universe = scenario.universe

        data = validate_success(
            api.get_submission(scenario.id, universe.coord_headers)
        )

        assert data["id"] == scenario.id
        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["total_raw_hours"] == approx_hours(8.00)
        assert data["total_direct_care_hours"] == approx_hours(8.00)
        assert data["total_excluded_hours"] == approx_hours(0.00)
        assert data["total_rn_direct_care_hours"] == approx_hours(8.00)
        assert data["total_resident_days"] == 5
        assert data["vendor_sourced_hours"] == approx_hours(0.00)
        assert data["amendment_index"] == 0
        assert data["amendment_surcharge_cents"] == 0
        assert data["waived_surcharge_cents"] == 0
        assert_instant_equals(
            data["correction_deadline"],
            TEST_DEFAULTS["PERIOD_CORRECTION_END"],
            "correction_deadline",
        )


class TestSubmissionListing:
    def test_01_the_status_filter_and_the_window_compose(
        self, api, accepted_quarter, reading_auditor_headers
    ):
        """PRD: "Quarterly submissions may be filtered by `facility_id`,
        `reporting_period_id`, `validated_by_worker_id`, `attested_by_worker_id`, and
        `status`." PRD: "The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`, where `total_count` is the size of the
        filtered result set before the window is applied and `has_more` indicates
        whether rows remain beyond the window."

        Design: Corner/entities/submissions_listing_filtered_by_status_returns_pagination_fields
        """
        scenario = accepted_quarter

        rows, meta = validate_paginated(
            api.list_submissions(
                reading_auditor_headers,
                {
                    "facility_id": scenario.facility_id,
                    "status": SubmissionStatus.ACCEPTED.value,
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == scenario.id
        assert rows[0]["status"] == SubmissionStatus.ACCEPTED.value
        assert rows[0]["audit_support_score"] == approx_score(100.00)

        _, draft_meta = validate_paginated(
            api.list_submissions(
                reading_auditor_headers,
                {
                    "facility_id": scenario.facility_id,
                    "status": SubmissionStatus.DRAFT.value,
                },
            )
        )
        assert draft_meta["total_count"] == 0


class TestCensusDayNotFound:
    def test_01_an_unminted_census_day_id_returns_the_census_not_found_code(
        self, api, platform_admin_headers
    ):
        """PRD: "each entity has its own not-found code: ... `ERR_CENSUS_DAY_NOT_FOUND`".
        PRD: "All error API responses (4xx status codes) follow this standard envelope
        format" whose "`error_id` is a unique, machine-readable string that identifies
        the specific error" and whose "`message` provides a human-readable explanation
        of what went wrong."

        Design: Corner/entities/census_day_get_unknown_id_returns_not_found
        """
        response = api.get_census_day(UNKNOWN_CENSUS_DAY_ID, platform_admin_headers)

        validate_error(response, ApiErrorId.ERR_CENSUS_DAY_NOT_FOUND.value)
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"].strip() != ""


class TestCensusDayRequiredFields:
    def test_01_omitting_the_resident_count_is_an_invalid_request(
        self, api, draft_submission
    ):
        """PRD: check 13 is "Every required body field for the endpoint is present and
        of the declared type — otherwise `ERR_INVALID_REQUEST`." PRD: "A **census day**
        is reported against a submission with the `submission_id`, the `census_date` in
        `YYYY-MM-DD` form, the facility-reported `resident_count` (zero or greater), and
        optionally `mds_resident_count`".

        Design: Corner/entities/census_day_create_missing_required_resident_count_returns_422
        """
        scenario = draft_submission
        universe = scenario.universe

        response = api.create_census_day(
            {"submission_id": scenario.id, "census_date": "2026-04-01"},
            universe.coord_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        _, meta = validate_paginated(
            api.list_census_days(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 0
        assert scenario.refresh()["version"] == 1


class TestDeclaredDefaults:
    def test_01_omitted_optional_fields_take_their_declared_defaults(
        self, api, universe, platform_admin_headers
    ):
        """PRD: "The optional boolean `weekend_countable` declares whether hours in
        this category count toward weekend staffing metrics and defaults to `true` when
        omitted." PRD: "`authorized_roles` is an array of role names the worker may act
        as, whose elements are drawn from `STAFFING_COORDINATOR` and
        `FACILITY_ADMINISTRATOR`, and which defaults to an empty array — meaning a
        worker registered without it cannot act at all." PRD: "A new worker starts with
        `status` `ACTIVE` and `reported_hours_total` at 0.00."

        Design: Corner/entities/job_category_and_worker_optional_fields_take_declared_defaults
        """
        category_payload = create_job_category_payload(
            code="LPN",
            cms_job_code=7,
            direct_care_class="DIRECT_CARE",
            nurse_group="LPN",
            direct_care_credit_pct=1.00,
        )
        category_payload.pop("weekend_countable")
        category = validate_success(
            api.create_job_category(category_payload, platform_admin_headers),
            expected_status=201,
        )
        assert category["weekend_countable"] is True

        worker = validate_success(
            api.create_worker(
                create_worker_payload(
                    universe.facility_id,
                    category["id"],
                    full_name="Morgan Practical",
                ),
                platform_admin_headers,
            ),
            expected_status=201,
        )
        assert worker["authorized_roles"] == []
        assert worker["vendor_id"] is None
        assert worker["status"] == WorkerStatus.ACTIVE.value
        assert worker["reported_hours_total"] == approx_hours(0.00)

    def test_02_an_omitted_mds_count_stays_null_and_blocks_reconciliation(
        self, api, draft_submission
    ):
        """PRD: a census day is reported "optionally `mds_resident_count`, the
        independently derived count used for reconciliation, which defaults to null
        when not yet supplied" and "On creation the day enters `status` `REPORTED`,
        `variance_pct` is null". PRD: reconciliation "requires `mds_resident_count` to
        be non-null (a null count is refused with `ERR_MDS_COUNT_MISSING`)".

        Design: Corner/entities/census_day_mds_resident_count_defaults_null_and_blocks_reconcile
        """
        scenario = draft_submission
        universe = scenario.universe

        day = validate_success(
            api.create_census_day(
                {
                    "submission_id": scenario.id,
                    "census_date": "2026-04-02",
                    "resident_count": 5,
                },
                universe.coord_headers,
            ),
            expected_status=201,
        )
        assert day["mds_resident_count"] is None
        assert day["variance_pct"] is None

        response = api.reconcile_census_day(day["id"], universe.coord_headers)
        validate_error(response, ApiErrorId.ERR_MDS_COUNT_MISSING.value)

        stored = validate_success(
            api.get_census_day(day["id"], universe.coord_headers)
        )
        assert stored["status"] == CensusDayStatus.REPORTED.value


class TestServerOwnedFields:
    def test_01_supplied_hour_and_credit_figures_are_ignored(
        self, api, draft_submission
    ):
        """PRD: "The shift length in hours, stored as `raw_hours`, is derived from the
        two times of day". PRD: "compute that line's direct-care contribution as
        `raw_hours` multiplied by the line's `percent` divided by 100, multiplied by the
        credit fraction, **then rounded half up to 2 decimal places**." PRD:
        "`excluded_hours` is `raw_hours` less `direct_care_hours`, rounded half up to 2
        decimal places — this is where non-direct-care and administrative time lands."

        Design: Corner/entities/hour_entry_computed_classification_input_ignored
        """
        scenario = draft_submission
        universe = scenario.universe

        payload = create_hour_entry_payload(
            scenario.id,
            universe.w_rn["id"],
            universe.jc_admin["id"],
            scenario.version,
            allocations=[allocation_line(universe.jc_admin["id"], 100.00)],
        )
        payload["raw_hours"] = 99.00
        payload["direct_care_hours"] = 99.00

        data = validate_success(
            api.create_hour_entry(payload, universe.coord_headers),
            expected_status=201,
        )

        assert data["raw_hours"] == approx_hours(8.00)
        assert data["direct_care_hours"] == approx_hours(0.00)
        assert data["excluded_hours"] == approx_hours(8.00)
        assert data["rn_hours"] == approx_hours(0.00)
        assert data["lpn_hours"] == approx_hours(0.00)
        assert data["na_hours"] == approx_hours(0.00)

        submission = scenario.refresh()
        assert submission["total_direct_care_hours"] == approx_hours(0.00)
        assert submission["total_excluded_hours"] == approx_hours(8.00)

    def test_02_a_supplied_id_and_version_do_not_reach_the_stored_facility(
        self, api, platform_admin_headers
    ):
        """PRD: "Every persisted resource carries a server-minted `id` formatted as a
        UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601
        UTC instant with three fractional digits" together with "`version`, an integer
        that begins at 1 on creation". PRD: "The five derived fields are seeded on
        registration: `posture` at `REPORTING_OPEN`, `open_case_count` at 0,
        `substantiated_case_count` at 0, `outstanding_surcharge_cents` at 0, and
        `latest_staffing_rating` at null."

        Design: Corner/entities/facility_system_fields_generated_input_ignored
        """
        payload = create_facility_payload(
            ccn="675003",
            name="Rosewood Skilled Nursing",
            certified_bed_count=60,
        )
        payload["id"] = CLAIMED_FACILITY_ID
        payload["version"] = 47

        data = validate_success(
            api.create_facility(payload, platform_admin_headers),
            expected_status=201,
        )

        assert data["version"] == 1
        assert data["id"] != CLAIMED_FACILITY_ID
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert data["posture"] == FacilityPosture.REPORTING_OPEN.value
        assert data["outstanding_surcharge_cents"] == 0
        assert data["latest_staffing_rating"] is None
        assert_facility(data)


class TestEnumTypeConstraints:
    def test_01_a_direct_care_class_outside_the_declared_set_is_refused(
        self, api, platform_admin_headers
    ):
        """PRD: check 14 is "Every enum-typed body field carries a value from that
        field's declared set — otherwise `ERR_INVALID_ENUM_VALUE`." PRD: a job category
        is defined with "a `direct_care_class` of `DIRECT_CARE`, `DIRECT_CARE_SPLIT`,
        `ADMINISTRATIVE`, or `NON_DIRECT_CARE`".

        Design: Corner/entities/job_category_invalid_direct_care_class_enum_rejected
        """
        response = api.create_job_category(
            create_job_category_payload(
                code="THERAPY",
                cms_job_code=12,
                direct_care_class="PARTIAL_CARE",
                nurse_group="NONE",
                direct_care_credit_pct=0.50,
            ),
            platform_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE.value)

        _, meta = validate_paginated(
            api.list_job_categories(platform_admin_headers, {"code": "THERAPY"})
        )
        assert meta["total_count"] == 0


class TestPayrollRecordImmutability:
    def test_01_a_filed_payroll_document_carries_no_version_and_no_updated_at(
        self, api, supported_quarter
    ):
        """PRD: "`PayrollRecord` is the single exception. A filed payroll document is
        immutable evidence: it carries only `id` and `created_at`. Both `updated_at`
        and `version` are absent from a `PayrollRecord` payload entirely."

        Design: Corner/entities/payroll_record_is_immutable_with_no_version_and_no_write_back
        """
        scenario = supported_quarter
        universe = scenario.universe
        record = scenario.payroll_records[0]

        data = validate_success(
            api.get_payroll_record(record["id"], universe.coord_headers)
        )

        assert "version" not in data
        assert "updated_at" not in data
        assert is_iso8601_timestamp(data["created_at"])
        assert data["paid_hours"] == approx_hours(8.00)
        assert data["support_type"] == "TIMECARD"
        assert data["document_ref"] == "TC-B0401"
        assert_payroll_record(data)


class TestBodyForeignKeyResolution:
    def test_01_an_unknown_submission_parent_is_refused_before_anything_else(
        self, api, draft_submission
    ):
        """PRD: check 12 is "Every foreign key in the request body resolves, including
        those nested inside allocation lines and agency batch lines — otherwise the
        corresponding not-found code", and the code for a submission is
        `ERR_SUBMISSION_NOT_FOUND`.

        Design: Corner/entities/hour_entry_unknown_submission_parent_returns_not_found
        """
        scenario = draft_submission
        universe = scenario.universe

        response = api.create_hour_entry(
            create_hour_entry_payload(
                UNKNOWN_SUBMISSION_ID,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
            ),
            universe.coord_headers,
        )
        validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_FOUND.value)

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 0

    def test_02_an_unknown_job_category_inside_an_allocation_line_is_refused(
        self, api, draft_submission
    ):
        """PRD: "Foreign keys supplied in a request body are resolved with the same
        codes, and the resolution reaches inside arrays: every `job_category_id` named
        by an allocation line must resolve, and every `worker_id` and `job_category_id`
        named by a line of an agency batch must resolve, or the whole request is
        refused."

        Design: Corner/entities/hour_entry_unknown_allocation_job_category_returns_not_found
        """
        scenario = draft_submission
        universe = scenario.universe

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                allocations=[
                    allocation_line(universe.jc_rn["id"], 60.00),
                    allocation_line(UNKNOWN_JOB_CATEGORY_ID, 40.00),
                ],
            ),
            universe.coord_headers,
        )
        validate_error(response, ApiErrorId.ERR_JOB_CATEGORY_NOT_FOUND.value)

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 0
        assert scenario.refresh()["version"] == 1
