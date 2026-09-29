"""Rule violations mapped to their declared error identifiers, the satisfying
cases that must pass, and one pinned precedence between two of them."""

from test_helpers import (
    ApiErrorId,
    AppealGrounds,
    AppealScenario,
    AppealStatus,
    AuditStatus,
    CaseScenario,
    CaseStatus,
    CaseTriggerReason,
    DirectCareClass,
    FacilityPosture,
    FindingCode,
    FindingStatus,
    NurseGroup,
    PublicationStatus,
    SubmissionStatus,
    SupportType,
    TEST_DEFAULTS,
    VendorScenario,
    VendorStatus,
    VendorSubmissionStatus,
    WorkerType,
    allocation_line,
    approx_hours,
    approx_ratio,
    assert_instant_equals,
    build_accepted_quarter,
    build_draft_submission,
    build_published_measure,
    create_census_day_payload,
    create_facility_payload,
    create_hour_entry_payload,
    create_job_category_payload,
    create_payroll_record_payload,
    create_rating_appeal_payload,
    create_reporting_period_payload,
    create_staffing_measure_payload,
    create_submission_payload,
    create_vendor_payload,
    create_vendor_submission_payload,
    create_worker_payload,
    make_state_auditor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FINDING_AUDITOR_USER_ID = "auditor-find-01"
VENDOR_AUDITOR_USER_ID = "auditor-vendor-01"
LATE_CLOCK = "2026-09-15T00:00:00Z"
WAIVER_NOTE = (
    "Single-resident census confirmed against the MDS extract; hprd is real."
)
CASE_DETAIL = "Night-shift RN hours are not corroborated by the timecard batch."


class TestHourEntryTemporalGuards:
    def test_01_the_three_temporal_guards_each_report_their_own_error(
        self, api, draft_submission
    ):
        """PRD: "The `work_date` must fall within the period's `start_date` through
        `end_date` inclusive (`ERR_WORK_DATE_OUTSIDE_PERIOD`) and must be on or after the
        worker's `hire_date` (`ERR_WORK_DATE_BEFORE_HIRE`)." PRD: "`shift_end` must be
        strictly later than `shift_start` on the same `work_date`
        (`ERR_SHIFT_WINDOW_INVALID`)."

        Design: Corner/validations/hour_entry_temporal_boundary_violations_rejected
        """
        scenario = draft_submission
        universe = scenario.universe
        late_hire = universe.register_worker(
            universe.facility_id,
            universe.jc_rn["id"],
            full_name="Skye Latehire",
            hire_date="2026-04-15",
            authorized_roles=[],
        )

        outside = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-05-01",
            ),
            universe.coord_headers,
        )
        validate_error(outside, ApiErrorId.ERR_WORK_DATE_OUTSIDE_PERIOD.value)

        before_hire = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                late_hire["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-10",
            ),
            universe.coord_headers,
        )
        validate_error(before_hire, ApiErrorId.ERR_WORK_DATE_BEFORE_HIRE.value)

        inverted = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-02",
                shift_start="15:00",
                shift_end="07:00",
            ),
            universe.coord_headers,
        )
        validate_error(inverted, ApiErrorId.ERR_SHIFT_WINDOW_INVALID.value)

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 0
        assert scenario.refresh()["version"] == 1


class TestAllocationSumAndDailyCeiling:
    def test_01_a_ninety_percent_split_and_a_twenty_one_hour_day_are_both_refused(
        self, api, draft_submission
    ):
        """PRD: "the `percent` values must sum to exactly 100.00 — an empty array or a
        sum that misses 100.00 in either direction is refused with
        `ERR_ALLOCATION_SUM_INVALID`." PRD: "the sum of `raw_hours` across all `ACTIVE`
        hour entries for the same `worker_id` on the same `work_date`, counting the new
        entry, may not exceed 20.00 hours; exceeding that ceiling is refused with
        `ERR_DAILY_HOURS_EXCEEDED`." PRD: "Touching endpoints do not intersect".

        Design: Corner/validations/hour_entry_allocation_sum_and_daily_cap_violations_rejected
        """
        scenario = draft_submission
        universe = scenario.universe
        long_shift = scenario.capture_hours(
            work_date="2026-04-02", shift_start="00:00", shift_end="16:00"
        )
        assert long_shift["raw_hours"] == approx_hours(16.00)
        version_after_setup = scenario.refresh()["version"]

        short_sum = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                version_after_setup,
                work_date="2026-04-03",
                allocations=[
                    allocation_line(universe.jc_rn["id"], 60.00),
                    allocation_line(universe.jc_split["id"], 30.00),
                ],
            ),
            universe.coord_headers,
        )
        validate_error(short_sum, ApiErrorId.ERR_ALLOCATION_SUM_INVALID.value)

        over_ceiling = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                version_after_setup,
                work_date="2026-04-02",
                shift_start="16:00",
                shift_end="21:00",
            ),
            universe.coord_headers,
        )
        validate_error(over_ceiling, ApiErrorId.ERR_DAILY_HOURS_EXCEEDED.value)

        data = scenario.refresh()
        assert data["total_raw_hours"] == approx_hours(16.00)
        assert data["version"] == version_after_setup


class TestAllocationSumExactlyOneHundred:
    def test_01_a_three_way_split_that_sums_to_one_hundred_is_accepted(
        self, api, draft_submission
    ):
        """PRD: "For each line in turn, resolve its `job_category_id` to a job category,
        read that category's `direct_care_credit_pct`, and compute that line's
        direct-care contribution as `raw_hours` multiplied by the line's `percent`
        divided by 100, multiplied by the credit fraction, **then rounded half up to 2
        decimal places**. `direct_care_hours` is the sum of those already-rounded
        per-line values."

        Design: Corner/validations/allocation_percents_summing_to_exactly_one_hundred_pass
        """
        scenario = draft_submission
        universe = scenario.universe

        data = validate_success(
            api.create_hour_entry(
                create_hour_entry_payload(
                    scenario.id,
                    universe.w_rn["id"],
                    universe.jc_rn["id"],
                    scenario.version,
                    work_date="2026-04-07",
                    allocations=[
                        allocation_line(universe.jc_rn["id"], 33.34),
                        allocation_line(universe.jc_split["id"], 33.33),
                        allocation_line(universe.jc_admin["id"], 33.33),
                    ],
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        assert data["raw_hours"] == approx_hours(8.00)
        assert data["direct_care_hours"] == approx_hours(4.27)
        assert data["excluded_hours"] == approx_hours(3.73)
        assert data["rn_hours"] == approx_hours(4.27)
        assert data["allocation_revision"] == 0


class TestPayrollFilingGuards:
    def test_01_capacity_duplicate_reference_and_support_mismatch_each_report_their_own_error(
        self, api, draft_submission
    ):
        """PRD: "The sum may not exceed 24.00 hours multiplied by that day count;
        exceeding it is refused with `ERR_PAYROLL_CAPACITY_EXCEEDED`." PRD: "an immutable
        external `document_ref` that must be unique within that `facility_id`; a
        collision is refused with `ERR_DUPLICATE_DOCUMENT_REF`." PRD: "When a
        `payroll_record_id` is offered, that document's `worker_id` must equal the entry's
        `worker_id` and the `work_date` must fall within the document's
        `pay_period_start` through `pay_period_end` inclusive; otherwise the hour is
        refused with `ERR_PAYROLL_SUPPORT_MISMATCH`."

        Design: Corner/validations/payroll_capacity_document_ref_and_support_violations_rejected
        """
        scenario = draft_submission
        universe = scenario.universe
        journal = validate_success(
            api.create_payroll_record(
                create_payroll_record_payload(
                    universe.facility_id,
                    universe.w_rn["id"],
                    pay_period_start="2026-04-01",
                    pay_period_end="2026-04-02",
                    paid_hours=47.00,
                    support_type=SupportType.PAYROLL_JOURNAL.value,
                    document_ref="PJ-APR-01",
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        over_capacity = api.create_payroll_record(
            create_payroll_record_payload(
                universe.facility_id,
                universe.w_rn["id"],
                pay_period_start="2026-04-02",
                pay_period_end="2026-04-02",
                paid_hours=20.00,
                document_ref="TC-APR-02",
            ),
            universe.coord_headers,
        )
        validate_error(over_capacity, ApiErrorId.ERR_PAYROLL_CAPACITY_EXCEEDED.value)

        duplicate_ref = api.create_payroll_record(
            create_payroll_record_payload(
                universe.facility_id,
                universe.w_rn["id"],
                pay_period_start="2026-04-10",
                pay_period_end="2026-04-10",
                paid_hours=8.00,
                document_ref="PJ-APR-01",
            ),
            universe.coord_headers,
        )
        validate_error(duplicate_ref, ApiErrorId.ERR_DUPLICATE_DOCUMENT_REF.value)

        uncovered_date = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-04-05",
                payroll_record_id=journal["id"],
            ),
            universe.coord_headers,
        )
        validate_error(uncovered_date, ApiErrorId.ERR_PAYROLL_SUPPORT_MISMATCH.value)

        _, meta = validate_paginated(
            api.list_payroll_records(
                universe.coord_headers, {"worker_id": universe.w_rn["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestCensusAndSubmissionUniqueness:
    def test_01_uniqueness_is_scoped_to_the_submission_and_to_the_facility_period_pair(
        self, api, draft_submission
    ):
        """PRD: "`census_date` must be unique within the submission
        (`ERR_DUPLICATE_CENSUS_DAY`) and must fall within the period's `start_date`
        through `end_date` inclusive (`ERR_CENSUS_DATE_OUTSIDE_PERIOD`)." PRD: "at most
        one submission whose `status` is anything other than `VOID` may exist for that
        pair — a second attempt is refused with `ERR_DUPLICATE_SUBMISSION`."

        Design: Corner/validations/census_and_submission_duplicate_and_scope_violations_rejected
        """
        scenario = draft_submission
        universe = scenario.universe
        first_day = scenario.report_census("2026-04-01", 5, 5)

        repeated = api.create_census_day(
            create_census_day_payload(
                scenario.id,
                census_date="2026-04-01",
                resident_count=7,
                mds_resident_count=7,
            ),
            universe.coord_headers,
        )
        validate_error(repeated, ApiErrorId.ERR_DUPLICATE_CENSUS_DAY.value)

        outside = api.create_census_day(
            create_census_day_payload(
                scenario.id,
                census_date="2026-05-05",
                resident_count=7,
                mds_resident_count=7,
            ),
            universe.coord_headers,
        )
        validate_error(outside, ApiErrorId.ERR_CENSUS_DATE_OUTSIDE_PERIOD.value)

        second_submission = api.create_submission(
            create_submission_payload(universe.facility_id, universe.period_id),
            universe.coord_headers,
        )
        validate_error(second_submission, ApiErrorId.ERR_DUPLICATE_SUBMISSION.value)

        _, meta = validate_paginated(
            api.list_census_days(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 1
        stored = validate_success(
            api.get_census_day(first_day["id"], universe.coord_headers)
        )
        assert stored["resident_count"] == 5


class TestConfigurationUniquenessAndShape:
    def test_01_each_reference_entity_enforces_its_own_uniqueness_or_shape_rule(
        self, api, universe, platform_admin_headers
    ):
        """PRD: the `ccn` "must be unique across every facility in the system; a
        collision is refused with `ERR_DUPLICATE_CCN`." PRD: "Two uniqueness rules apply
        at once and share the code `ERR_DUPLICATE_PERIOD_CODE`: `period_code` must be
        unused for that `state_code`, and `correction_window_end` must be strictly after
        `submission_deadline`." PRD: "a category declared `ADMINISTRATIVE` or
        `NON_DIRECT_CARE` must carry a `direct_care_credit_pct` of exactly 0.00, and a
        non-zero credit on such a class is refused with `ERR_DUPLICATE_JOB_CATEGORY` —
        the same code that guards `code` uniqueness." PRD: the vendor's "`tax_id` —
        unique within that `facility_id`, with a collision refused by
        `ERR_DUPLICATE_VENDOR_TAX_ID`".

        Design: Corner/validations/configuration_uniqueness_and_shape_violations_rejected
        """
        validate_success(
            api.create_vendor(
                create_vendor_payload(universe.facility_id), platform_admin_headers
            ),
            expected_status=201,
        )

        duplicate_ccn = api.create_facility(
            create_facility_payload(
                name="Duplicate Ridge Nursing", certified_bed_count=80
            ),
            platform_admin_headers,
        )
        validate_error(duplicate_ccn, ApiErrorId.ERR_DUPLICATE_CCN.value)

        repeated_code = api.create_reporting_period(
            create_reporting_period_payload(
                start_date="2026-10-01",
                end_date="2026-10-31",
                submission_deadline="2027-02-14T23:59:59Z",
                correction_window_end="2027-04-30T23:59:59Z",
            ),
            platform_admin_headers,
        )
        validate_error(repeated_code, ApiErrorId.ERR_DUPLICATE_PERIOD_CODE.value)

        inverted_window = api.create_reporting_period(
            create_reporting_period_payload(
                period_code="2026Q4",
                start_date="2026-10-01",
                end_date="2026-10-31",
                submission_deadline="2027-02-14T23:59:59Z",
                correction_window_end="2027-01-14T23:59:59Z",
            ),
            platform_admin_headers,
        )
        validate_error(inverted_window, ApiErrorId.ERR_DUPLICATE_PERIOD_CODE.value)

        repeated_category = api.create_job_category(
            create_job_category_payload(cms_job_code=6), platform_admin_headers
        )
        validate_error(repeated_category, ApiErrorId.ERR_DUPLICATE_JOB_CATEGORY.value)

        credited_non_direct = api.create_job_category(
            create_job_category_payload(
                code="HOUSEKEEPING",
                cms_job_code=20,
                direct_care_class=DirectCareClass.NON_DIRECT_CARE.value,
                nurse_group=NurseGroup.NONE.value,
                direct_care_credit_pct=0.50,
            ),
            platform_admin_headers,
        )
        validate_error(credited_non_direct, ApiErrorId.ERR_DUPLICATE_JOB_CATEGORY.value)

        duplicate_tax_id = api.create_vendor(
            create_vendor_payload(
                universe.facility_id,
                vendor_name="Northgate Agency Staffing Two",
                attestation_contact="ops2@northgate.example",
            ),
            platform_admin_headers,
        )
        validate_error(duplicate_tax_id, ApiErrorId.ERR_DUPLICATE_VENDOR_TAX_ID.value)

        _, period_meta = validate_paginated(
            api.list_reporting_periods(
                platform_admin_headers,
                {"state_code": TEST_DEFAULTS["FACILITY_STATE_CODE"]},
            )
        )
        assert period_meta["total_count"] == 1
        _, category_meta = validate_paginated(
            api.list_job_categories(platform_admin_headers, {"code": "RN"})
        )
        assert category_meta["total_count"] == 1


class TestVendorRosterAndBatchShape:
    def test_01_the_linkage_biconditional_the_empty_batch_and_the_suspended_vendor(
        self, api, universe
    ):
        """PRD: "`vendor_id` links the worker to a staffing agency and is governed by a
        strict biconditional: it must be supplied exactly when `worker_type` is
        `AGENCY_CONTRACTOR`, and must be absent (defaulting to null) for the other two
        worker types; violating either direction is refused with
        `ERR_VENDOR_LINKAGE_INVALID`." PRD: a batch names "a `lines` array with at least
        one element — an empty array is refused with `ERR_VENDOR_LINES_EMPTY`." PRD:
        "Suspending a vendor moves its `status` from `ACTIVE` to `SUSPENDED`, which
        blocks new batch creation, batch submission, and batch acceptance with
        `ERR_VENDOR_SUSPENDED`."

        Design: Corner/validations/vendor_roster_batch_shape_and_suspension_violations_rejected
        """
        vendor = VendorScenario(universe)
        vendor.file_batch([vendor.batch_line("2026-04-02")])

        linked_employee = api.create_worker(
            create_worker_payload(
                universe.facility_id,
                universe.jc_rn["id"],
                full_name="Jules Employee",
                vendor_id=vendor.vendor_id,
            ),
            universe.admin_headers,
        )
        validate_error(linked_employee, ApiErrorId.ERR_VENDOR_LINKAGE_INVALID.value)

        unlinked_contractor = api.create_worker(
            create_worker_payload(
                universe.facility_id,
                universe.jc_rn["id"],
                full_name="Robin Unlinked",
                worker_type=WorkerType.AGENCY_CONTRACTOR.value,
            ),
            universe.admin_headers,
        )
        validate_error(unlinked_contractor, ApiErrorId.ERR_VENDOR_LINKAGE_INVALID.value)

        empty_batch = api.create_vendor_submission(
            create_vendor_submission_payload(
                vendor.vendor_id, universe.facility_id, universe.period_id, []
            ),
            universe.admin_headers,
        )
        validate_error(empty_batch, ApiErrorId.ERR_VENDOR_LINES_EMPTY.value)

        suspended = validate_success(
            api.suspend_vendor(
                vendor.vendor_id,
                make_state_auditor_headers(VENDOR_AUDITOR_USER_ID),
            )
        )
        assert suspended["status"] == VendorStatus.SUSPENDED.value

        blocked = api.submit_vendor_submission(
            vendor.batch["id"], vendor.vendor_headers
        )
        validate_error(blocked, ApiErrorId.ERR_VENDOR_SUSPENDED.value)
        assert vendor.refresh()["status"] == VendorSubmissionStatus.DRAFT.value

        _, worker_meta = validate_paginated(
            api.list_workers(
                universe.admin_headers, {"facility_id": universe.facility_id}
            )
        )
        assert worker_meta["total_count"] == 4
        _, vendor_meta = validate_paginated(
            api.list_vendors(
                universe.admin_headers,
                {
                    "facility_id": universe.facility_id,
                    "status": VendorStatus.SUSPENDED.value,
                },
            )
        )
        assert vendor_meta["total_count"] == 1
        batches, batch_meta = validate_paginated(
            api.list_vendor_submissions(
                universe.admin_headers, {"vendor_id": vendor.vendor_id}
            )
        )
        assert batch_meta["total_count"] == 1
        assert batches[0]["status"] == VendorSubmissionStatus.DRAFT.value


class TestFatalFindingBlocksAttestation:
    def test_01_waiving_the_fatal_finding_is_what_unblocks_the_quarter(
        self, api, client
    ):
        """PRD: "`HPRD_IMPLAUSIBLE`, `severity` `FATAL`, a single finding with
        `subject_ref` set to the literal string `PERIOD`, raised when the as-submitted
        `hprd_reported` exceeds 12.0000." PRD: attestation "requires ...
        `open_fatal_finding_count` to be exactly 0 (`ERR_FATAL_FINDINGS_OPEN`)". PRD:
        waiving "moves `status` to `WAIVED`, records `waived_by_user_id` from the acting
        identity, stamps `resolved_at`, appends the `waiver_note` to the finding's
        `detail`, refreshes the submission's `open_fatal_finding_count`".

        Design: Corner/validations/submit_blocked_by_open_fatal_finding_then_allowed_after_waiver
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        scenario.capture_hours(
            work_date="2026-04-01", shift_start="00:00", shift_end="16:00"
        )
        scenario.report_census("2026-04-01", 1, 1)

        validated = scenario.validate()
        assert validated["hprd_reported"] == approx_ratio(16.0000)
        assert validated["open_fatal_finding_count"] == 1

        auditor_headers = make_state_auditor_headers(FINDING_AUDITOR_USER_ID)
        findings, _ = validate_paginated(
            api.list_submission_findings(
                scenario.id,
                auditor_headers,
                {
                    "code": FindingCode.HPRD_IMPLAUSIBLE.value,
                    "status": FindingStatus.OPEN.value,
                },
            )
        )
        assert len(findings) == 1
        assert findings[0]["subject_ref"] == "PERIOD"

        blocked = api.submit_submission(scenario.id, universe.fac_admin_headers)
        validate_error(blocked, ApiErrorId.ERR_FATAL_FINDINGS_OPEN.value)
        assert scenario.refresh()["status"] == SubmissionStatus.VALIDATED.value

        waived = scenario.waive(
            findings[0]["id"], WAIVER_NOTE, user_id=FINDING_AUDITOR_USER_ID
        )
        assert waived["status"] == FindingStatus.WAIVED.value
        assert waived["waived_by_user_id"] == FINDING_AUDITOR_USER_ID
        assert scenario.refresh()["open_fatal_finding_count"] == 0

        attested = validate_success(
            api.submit_submission(scenario.id, universe.fac_admin_headers)
        )
        assert attested["status"] == SubmissionStatus.SUBMITTED.value
        assert attested["attested_by_worker_id"] == universe.w_admin["id"]


class TestSanctionedFacilityBlocksValidation:
    def test_01_a_sanction_earned_in_april_blocks_the_july_validation(
        self, api, client
    ):
        """PRD: check 32 is "On the validation pass and on measure publication, the
        owning facility's `posture` is not `SANCTIONED` — otherwise
        `ERR_FACILITY_SANCTIONED`." PRD: substantiation "sets it to `SANCTIONED` and
        refreshes `substantiated_case_count` and `open_case_count`" and "every
        `VALIDATED` submission of that facility reverts to `DRAFT`".

        Design: Corner/validations/sanctioned_facility_cannot_validate_a_later_period
        """
        scenario = build_accepted_quarter(client)
        universe = scenario.universe
        later_period = universe.open_period(
            period_code=TEST_DEFAULTS["SECOND_PERIOD_CODE"],
            start_date=TEST_DEFAULTS["SECOND_PERIOD_START"],
            end_date=TEST_DEFAULTS["SECOND_PERIOD_END"],
            submission_deadline=TEST_DEFAULTS["SECOND_PERIOD_DEADLINE"],
            correction_window_end=TEST_DEFAULTS["SECOND_PERIOD_CORRECTION_END"],
        )
        later_submission = validate_success(
            api.create_submission(
                create_submission_payload(universe.facility_id, later_period["id"]),
                universe.coord_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_census_day(
                create_census_day_payload(
                    later_submission["id"],
                    census_date="2026-07-01",
                    resident_count=5,
                    mds_resident_count=5,
                ),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        case = CaseScenario(
            scenario,
            trigger_reason=CaseTriggerReason.UNSUPPORTED_HOURS.value,
            detail=CASE_DETAIL,
        )
        case.request_info("Send the 2026-04-01 timecards.")
        case.respond("Timecards attached.")
        substantiated = case.substantiate(
            "Timecards do not cover the reported night hours."
        )
        assert substantiated["status"] == CaseStatus.SUBSTANTIATED.value

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.SANCTIONED.value
        assert facility["substantiated_case_count"] == 1

        response = api.validate_submission(
            later_submission["id"], universe.coord_headers
        )
        validate_error(response, ApiErrorId.ERR_FACILITY_SANCTIONED.value)

        later = validate_success(
            api.get_submission(later_submission["id"], universe.coord_headers)
        )
        assert later["status"] == SubmissionStatus.DRAFT.value
        assert later["hprd_reported"] is None
        assert scenario.refresh()["status"] == SubmissionStatus.ACCEPTED.value


class TestCaseStateResponseAndScope:
    def test_01_the_due_process_guard_fires_from_a_status_substantiation_accepts(
        self, api, client
    ):
        """PRD: the facility response "is permitted only from `INFO_REQUESTED`". PRD:
        "**Substantiation** is permitted from either `INFO_REQUESTED` or `UNDER_REVIEW`,
        but in both cases only after the facility has been heard at least once: the
        case's `facility_response_count` must be at least 1, and a substantiation
        attempted before any response is refused with `ERR_CASE_RESPONSE_REQUIRED`."
        PRD: "the named submission's `facility_id` must equal the case's `facility_id`
        ... either mismatch is refused with `ERR_CASE_SUBMISSION_MISMATCH`."

        Design: Corner/validations/case_state_response_and_submission_scope_violations_rejected
        """
        scenario = build_accepted_quarter(client)
        universe = scenario.universe
        case = CaseScenario(
            scenario,
            trigger_reason=CaseTriggerReason.UNSUPPORTED_HOURS.value,
            detail=CASE_DETAIL,
        )

        early_response = api.respond_to_case(
            case.id,
            {"response_note": "Responding before any information was requested."},
            universe.fac_admin_headers,
        )
        validate_error(early_response, ApiErrorId.ERR_CASE_STATE_INVALID.value)

        requested = case.request_info("Send the 2026-04-01 timecards.")
        assert requested["status"] == CaseStatus.INFO_REQUESTED.value
        assert requested["info_request_count"] == 1
        assert requested["facility_response_count"] == 0

        premature = api.substantiate_case(
            case.id,
            {"resolution_note": "Substantiating without waiting for the facility."},
            case.auditor_headers,
        )
        validate_error(premature, ApiErrorId.ERR_CASE_RESPONSE_REQUIRED.value)

        other_facility = validate_success(
            api.create_facility(
                create_facility_payload(
                    ccn=TEST_DEFAULTS["SECOND_FACILITY_CCN"],
                    name="Willow Bend Care",
                    certified_bed_count=TEST_DEFAULTS["SECOND_FACILITY_BED_COUNT"],
                ),
                universe.admin_headers,
            ),
            expected_status=201,
        )
        other_submission = validate_success(
            api.create_submission(
                create_submission_payload(
                    other_facility["id"], universe.period_id
                ),
                universe.admin_headers,
            ),
            expected_status=201,
        )

        cross_facility = api.create_discrepancy_case(
            {
                "facility_id": universe.facility_id,
                "submission_id": other_submission["id"],
                "trigger_reason": CaseTriggerReason.CENSUS_MISMATCH.value,
                "detail": "Case filed against the wrong facility's submission.",
            },
            case.auditor_headers,
        )
        validate_error(cross_facility, ApiErrorId.ERR_CASE_SUBMISSION_MISMATCH.value)

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.AUDIT_HOLD.value
        assert facility["open_case_count"] == 1
        assert facility["substantiated_case_count"] == 0


class TestMeasureDuplicationAndFreeze:
    def test_01_a_published_measure_blocks_a_second_computation_then_the_freeze_does(
        self, api, client, cms_publisher_headers
    ):
        """PRD: computation "requires that no measure with `publication_status`
        `PROVISIONAL` or `PUBLISHED` already exists for that submission
        (`ERR_DUPLICATE_MEASURE`), and requires that no existing measure for that
        submission be frozen with `audit_status` `UNDER_AUDIT`
        (`ERR_MEASURE_UNDER_AUDIT`)." PRD: check 25 is "On measure computation and
        measure publication, no existing `StaffingMeasure` for the submission has
        `audit_status` `UNDER_AUDIT` — otherwise `ERR_MEASURE_UNDER_AUDIT`", and it
        precedes check 62 on duplicate measures.

        Design: Corner/validations/measure_duplicate_and_under_audit_violations_rejected
        """
        measure = build_published_measure(client)
        scenario = measure.scenario

        duplicate = api.create_staffing_measure(
            create_staffing_measure_payload(scenario.id), cms_publisher_headers
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_MEASURE.value)

        case = CaseScenario(
            scenario,
            trigger_reason=CaseTriggerReason.CENSUS_MISMATCH.value,
            detail="Reported census conflicts with the state register.",
            staffing_measure_id=measure.id,
        )
        case.request_info("Send the 2026-04-01 census register extract.")
        case.respond("Register extract attached.")
        assert measure.refresh()["audit_status"] == AuditStatus.UNDER_AUDIT.value

        frozen = api.create_staffing_measure(
            create_staffing_measure_payload(scenario.id), cms_publisher_headers
        )
        validate_error(frozen, ApiErrorId.ERR_MEASURE_UNDER_AUDIT.value)

        data = measure.refresh()
        assert data["publication_status"] == PublicationStatus.PUBLISHED.value
        assert data["has_open_appeal"] is False

        _, meta = validate_paginated(
            api.list_staffing_measures(
                cms_publisher_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 1


class TestAppealStateAndDuplication:
    def test_01_a_pending_appeal_blocks_a_second_and_a_denied_one_is_terminal(
        self, api, client
    ):
        """PRD: filing "requires that no appeal with `status` `SUBMITTED` already exist
        for that measure (`ERR_DUPLICATE_APPEAL`)". PRD: "Both require the appeal's
        `status` to be `SUBMITTED` (`ERR_APPEAL_STATE_INVALID`) and the appealed
        measure's `publication_status` to still be `PUBLISHED`". PRD: "**Denying** moves
        the appeal's `status` to the terminal `DENIED` and clears the appealed measure's
        `has_open_appeal`."

        Design: Corner/validations/appeal_state_and_duplicate_violations_rejected
        """
        measure = build_published_measure(client)
        scenario = measure.scenario
        universe = scenario.universe
        appeal = AppealScenario(
            measure,
            narrative="One RN shift was keyed against the wrong job category.",
        )

        second = api.create_rating_appeal(
            create_rating_appeal_payload(
                measure.id,
                measure.version,
                grounds=AppealGrounds.CENSUS_ERROR.value,
                narrative="A second appeal filed while the first is pending.",
            ),
            universe.fac_admin_headers,
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_APPEAL.value)

        denied = appeal.deny("The keying error does not change the star rating.")
        assert denied["status"] == AppealStatus.DENIED.value
        assert denied["decided_by_user_id"] == "reviewer-01"
        assert measure.refresh()["has_open_appeal"] is False

        late_grant = api.grant_rating_appeal(
            appeal.id,
            {"decision_note": "Attempting to grant an already decided appeal."},
            appeal.reviewer_headers,
        )
        validate_error(late_grant, ApiErrorId.ERR_APPEAL_STATE_INVALID.value)

        assert (
            measure.refresh()["publication_status"]
            == PublicationStatus.PUBLISHED.value
        )
        assert scenario.refresh()["waived_surcharge_cents"] == 0


class TestAppealWindow:
    def test_01_an_appeal_filed_six_weeks_after_publication_is_refused(
        self, api, client
    ):
        """PRD: filing "requires the logical clock to be at or before that measure's
        `appeal_deadline` — the instant 30 calendar days after publication — with a later
        filing refused as `ERR_APPEAL_WINDOW_CLOSED`". PRD: "Publishing stamps
        `published_at` with the logical clock instant, sets `appeal_deadline` to
        `published_at` plus 30 calendar days".

        Design: Corner/validations/appeal_filed_after_thirty_day_window_rejected
        """
        measure = build_published_measure(client)
        universe = measure.universe

        published = measure.refresh()
        assert_instant_equals(
            published["published_at"], "2026-08-01T00:00:00Z", "published_at"
        )
        assert_instant_equals(
            published["appeal_deadline"], "2026-08-31T00:00:00Z", "appeal_deadline"
        )
        version_before = published["version"]

        universe.set_clock(LATE_CLOCK)

        response = api.create_rating_appeal(
            create_rating_appeal_payload(
                measure.id,
                version_before,
                grounds=AppealGrounds.VENDOR_DATA_ERROR.value,
                narrative="Filed six weeks after publication.",
            ),
            universe.fac_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)

        data = measure.refresh()
        assert data["has_open_appeal"] is False
        assert data["version"] == version_before

        _, meta = validate_paginated(
            api.list_rating_appeals(
                universe.fac_admin_headers, {"staffing_measure_id": measure.id}
            )
        )
        assert meta["total_count"] == 0


class TestSurchargeCap:
    def test_01_the_second_amendment_breaches_the_facility_wide_cap(
        self, api, client
    ):
        """PRD: "If the facility's current `outstanding_surcharge_cents` plus the
        surcharge this reopen would assess exceeds 50000 cents, the reopen is refused
        with `ERR_SURCHARGE_CAP_EXCEEDED` and no state change of any kind is applied — no
        index increment, no fee accrual, no status move." PRD: the base fee "is 25000
        cents plus 2500 cents for each amendment beyond the first, that is, 2500 cents
        multiplied by one less than the prospective amendment index."

        Design: Corner/validations/second_reopen_exceeds_surcharge_cap_rejected
        """
        scenario = build_accepted_quarter(client)
        universe = scenario.universe
        scenario.reopen()
        scenario.validate()
        scenario.submit()
        scenario.accept()

        after_first = scenario.refresh()
        assert after_first["amendment_index"] == 1
        assert after_first["amendment_surcharge_cents"] == 25000
        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 25000

        response = api.reopen_submission(scenario.id, universe.coord_headers)
        validate_error(response, ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED.value)

        unchanged = scenario.refresh()
        assert unchanged["status"] == SubmissionStatus.ACCEPTED.value
        assert unchanged["amendment_index"] == 1
        assert unchanged["amendment_surcharge_cents"] == 25000
        facility_after = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility_after["outstanding_surcharge_cents"] == 25000


class TestRejectionPrecedence:
    def test_01_the_temporal_guard_outranks_the_allocation_sum_guard(
        self, api, draft_submission
    ):
        """PRD: "Checks are evaluated in the following order, and the first violation
        encountered wins." Check 36 is "On hour creation and on agency batch acceptance,
        `work_date` falls within the submission's period from `start_date` to `end_date`
        inclusive — otherwise `ERR_WORK_DATE_OUTSIDE_PERIOD`" and check 49 is "On hour
        creation, allocation replacement, and agency batch creation, the allocation set
        is non-empty and its percentages sum to exactly 100.00 — otherwise
        `ERR_ALLOCATION_SUM_INVALID`".

        Design: Corner/validations/work_date_outside_period_precedes_allocation_sum_invalid
        """
        scenario = draft_submission
        universe = scenario.universe

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.version,
                work_date="2026-05-15",
                allocations=[
                    allocation_line(universe.jc_rn["id"], 55.00),
                    allocation_line(universe.jc_split["id"], 20.00),
                ],
            ),
            universe.coord_headers,
        )
        validate_error(response, ApiErrorId.ERR_WORK_DATE_OUTSIDE_PERIOD.value)

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"submission_id": scenario.id}
            )
        )
        assert meta["total_count"] == 0
        assert scenario.refresh()["version"] == 1
