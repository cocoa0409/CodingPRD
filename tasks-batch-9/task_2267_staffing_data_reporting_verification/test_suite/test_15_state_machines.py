"""Declared transitions, their preconditions, and the side effects each one
either does or does not apply."""

from test_helpers import (
    ApiErrorId,
    AuditStatus,
    CaseScenario,
    CaseStatus,
    CaseTriggerReason,
    CensusDayStatus,
    DEFAULT_CLOCK,
    EntryStatus,
    FacilityPosture,
    FindingCode,
    FindingStatus,
    MeasureVariant,
    PublicationStatus,
    ReportingPeriodStatus,
    SubmissionStatus,
    TEST_DEFAULTS,
    VendorScenario,
    VendorSubmissionStatus,
    VerificationOutcome,
    VerificationStatus,
    approx_hours,
    approx_ratio,
    approx_score,
    assert_instant_equals,
    build_draft_submission,
    build_published_measure,
    create_hour_entry_payload,
    create_submission_payload,
    find_finding,
    validate_error,
    validate_paginated,
    validate_success,
    verify_hour_entry_payload,
)
from test_helpers.constants import ACCEPTING_AUDITOR_USER_ID

BATCH_REJECTION_REASON = "Line worker is not on our approved agency roster."
CASE_DETAIL = "Complaint alleges overstated night-shift RN coverage."
CASE_DISMISSAL = "Assignment sheet matches the reported hours."


class TestSubmissionInitialState:
    def test_01_a_new_quarter_opens_in_draft_with_every_rollup_zeroed(
        self, api, universe
    ):
        """PRD: "On creation the submission enters `DRAFT`, sets `amendment_index` to 0,
        sets every hour and money rollup to its zero value, sets `hprd_reported` and
        `weekend_hprd_reported` and `audit_support_score` to null, and copies the
        period's `correction_window_end` into `correction_deadline`."

        Design: Corner/state_machines/submission_initial_state_is_draft_with_zeroed_rollups
        """
        data = validate_success(
            api.create_submission(
                create_submission_payload(universe.facility_id, universe.period_id),
                universe.coord_headers,
            ),
            expected_status=201,
        )

        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["version"] == 1
        assert data["total_raw_hours"] == approx_hours(0.00)
        assert data["total_direct_care_hours"] == approx_hours(0.00)
        assert data["total_excluded_hours"] == approx_hours(0.00)
        assert data["total_resident_days"] == 0
        assert data["hprd_reported"] is None
        assert data["weekend_hprd_reported"] is None
        assert data["open_fatal_finding_count"] == 0
        assert data["open_warning_finding_count"] == 0
        assert data["audit_support_score"] is None
        assert_instant_equals(
            data["correction_deadline"],
            TEST_DEFAULTS["PERIOD_CORRECTION_END"],
            "correction_deadline",
        )


class TestVendorBatchSubmission:
    def test_01_attesting_the_batch_stamps_the_logical_clock_instant(
        self, api, universe
    ):
        """PRD: "The vendor representative attests the batch by submitting it, which
        moves `status` from `DRAFT` to `SUBMITTED`, stamps `submitted_at` with the
        logical clock instant, and clears any `rejection_reason` left over from an
        earlier round." PRD: "Before any clock write, the logical clock reads exactly
        `2026-08-01T00:00:00Z`".

        Design: Corner/state_machines/vendor_submission_draft_to_submitted_sets_submitted_at
        """
        vendor = VendorScenario(universe)
        vendor.file_batch([vendor.batch_line("2026-04-02")])

        data = vendor.submit_batch()

        assert data["status"] == VendorSubmissionStatus.SUBMITTED.value
        assert_instant_equals(data["submitted_at"], DEFAULT_CLOCK, "submitted_at")
        assert data["line_count"] == 1
        assert data["accepted_direct_care_hours"] == approx_hours(0.00)

        vendor_row = validate_success(
            api.get_vendor(vendor.vendor_id, universe.coord_headers)
        )
        assert vendor_row["accepted_hours_total"] == approx_hours(0.00)

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"vendor_submission_id": vendor.batch["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestValidationPreconditions:
    def test_01_a_quarter_with_no_census_day_cannot_be_validated(
        self, api, client
    ):
        """PRD: the validation pass "requires ... the submission to have at least one
        census day in `REPORTED`, `RECONCILED`, or `DISPUTED` — a submission with no
        census data at all is refused with `ERR_NO_CENSUS_DATA`." PRD: a successful run
        "records the acting worker's id as `validated_by_worker_id`, moves `status` from
        `DRAFT` to `VALIDATED`".

        Design: Corner/state_machines/validate_without_any_census_day_returns_no_census_data
        """
        scenario = build_draft_submission(client)
        scenario.capture_supported_hours()

        response = api.validate_submission(
            scenario.id, scenario.universe.coord_headers
        )
        validate_error(response, ApiErrorId.ERR_NO_CENSUS_DATA.value)

        data = scenario.refresh()
        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["validated_by_worker_id"] is None

        _, meta = validate_paginated(
            api.list_submission_findings(
                scenario.id, scenario.universe.coord_headers, {"limit": 100}
            )
        )
        assert meta["total_count"] == 0

    def test_02_verifying_an_unsupported_by_construction_hour_as_supported_is_refused(
        self, api, client, verifying_auditor_headers
    ):
        """PRD: "Recording `SUPPORTED` additionally requires the entry's
        `payroll_record_id` to be non-null; verifying an unsupported-by-construction
        hour as supported is refused with `ERR_SUPPORT_DOCUMENT_MISSING`." PRD:
        "Recording `UNSUPPORTED` imposes no documentation precondition."

        Design: Corner/state_machines/verify_supported_without_payroll_record_rejected
        """
        scenario = build_draft_submission(client)
        entry = scenario.capture_hours(work_date="2026-04-02")

        response = api.verify_hour_entry(
            entry["id"],
            verify_hour_entry_payload(VerificationOutcome.SUPPORTED.value),
            verifying_auditor_headers,
        )
        validate_error(response, ApiErrorId.ERR_SUPPORT_DOCUMENT_MISSING.value)

        stored = validate_success(
            api.get_hour_entry(entry["id"], scenario.universe.coord_headers)
        )
        assert stored["verification_status"] == VerificationStatus.UNVERIFIED.value
        assert stored["verified_by_user_id"] is None

        unsupported = validate_success(
            api.verify_hour_entry(
                entry["id"],
                verify_hour_entry_payload(VerificationOutcome.UNSUPPORTED.value),
                verifying_auditor_headers,
            )
        )
        assert (
            unsupported["verification_status"] == VerificationStatus.UNSUPPORTED.value
        )


class TestAcceptanceSideEffects:
    def test_01_acceptance_stores_the_sampled_score_and_opens_no_case_at_the_floor(
        self, api, submitted_quarter, accepting_auditor_headers
    ):
        """PRD: "Acceptance moves `status` to `ACCEPTED`, records `accepted_by_user_id`
        and stamps `accepted_at`, scores the quarter's audit readiness on a sampled
        basis and stores the result in `audit_support_score`, and increments `version` by
        one. When that score comes out below the risk floor of 70.00, the acceptance
        opens a discrepancy investigation on the spot".

        Design: Corner/state_machines/submission_accept_side_effects_store_audit_score_and_accepted_at
        """
        scenario = submitted_quarter
        universe = scenario.universe
        version_before = scenario.refresh()["version"]

        data = validate_success(
            api.accept_submission(scenario.id, accepting_auditor_headers)
        )

        assert data["status"] == SubmissionStatus.ACCEPTED.value
        assert data["accepted_by_user_id"] == ACCEPTING_AUDITOR_USER_ID
        assert_instant_equals(data["accepted_at"], DEFAULT_CLOCK, "accepted_at")
        assert data["audit_support_score"] == approx_score(100.00)
        assert data["version"] == version_before + 1

        _, meta = validate_paginated(
            api.list_discrepancy_cases(
                accepting_auditor_headers, {"facility_id": scenario.facility_id}
            )
        )
        assert meta["total_count"] == 0

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.REPORTING_OPEN.value
        assert facility["open_case_count"] == 0

    def test_02_accepting_a_draft_quarter_is_an_invalid_transition(
        self, api, supported_quarter, accepting_auditor_headers
    ):
        """PRD: check 18 is "The target `QuarterlySubmission` is in a status the
        requested operation accepts — otherwise `ERR_SUBMISSION_STATE_INVALID`" and
        "acceptance and rejection accept `SUBMITTED`".

        Design: Corner/state_machines/accept_from_draft_is_rejected_as_invalid_transition
        """
        scenario = supported_quarter
        universe = scenario.universe

        response = api.accept_submission(scenario.id, accepting_auditor_headers)
        validate_error(response, ApiErrorId.ERR_SUBMISSION_STATE_INVALID.value)

        data = scenario.refresh()
        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["accepted_at"] is None
        assert data["audit_support_score"] is None

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.REPORTING_OPEN.value


class TestPeriodCloseLockdown:
    def test_01_a_finalized_quarter_cannot_be_reopened_once_the_period_is_closed(
        self, api, accepted_quarter, platform_admin_headers
    ):
        """PRD: "Closing moves the period's `status` from `OPEN` to `CLOSED` and sweeps
        every submission of that period in one pass: each `ACCEPTED` submission moves to
        `FINAL`". PRD: check 17 is "The governing `ReportingPeriod` is `OPEN` — otherwise
        `ERR_PERIOD_CLOSED`", which precedes check 18 on submission status.

        Design: Corner/state_machines/reopen_after_period_close_is_blocked_by_period_closed
        """
        scenario = accepted_quarter
        universe = scenario.universe

        period = validate_success(
            api.close_reporting_period(universe.period_id, platform_admin_headers)
        )
        assert period["status"] == ReportingPeriodStatus.CLOSED.value
        assert scenario.refresh()["status"] == SubmissionStatus.FINAL.value

        response = api.reopen_submission(scenario.id, universe.coord_headers)
        validate_error(response, ApiErrorId.ERR_PERIOD_CLOSED.value)

        data = scenario.refresh()
        assert data["amendment_index"] == 0
        assert data["amendment_surcharge_cents"] == 0

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 0

    def test_02_closing_a_period_voids_the_quarter_that_was_never_accepted(
        self, api, client, platform_admin_headers
    ):
        """PRD: "each submission still sitting in `DRAFT`, `VALIDATED`, or `REJECTED`
        moves to `VOID`, since it was never accepted." PRD:
        "`outstanding_surcharge_cents` is the sum, over every `QuarterlySubmission` of
        the facility whose `status` is anything other than `VOID`, of that submission's
        `amendment_surcharge_cents` less its `waived_surcharge_cents`."

        Design: Corner/state_machines/period_close_voids_never_accepted_submission
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        scenario.capture_supported_hours()
        scenario.report_census("2026-04-01", 5, 5)

        period = validate_success(
            api.close_reporting_period(universe.period_id, platform_admin_headers)
        )
        assert period["status"] == ReportingPeriodStatus.CLOSED.value
        assert scenario.refresh()["status"] == SubmissionStatus.VOID.value

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 0

        response = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                scenario.refresh()["version"],
                work_date="2026-04-03",
            ),
            universe.coord_headers,
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_CLOSED.value)


class TestRepeatedTriggersAreRefused:
    def test_01_a_second_validation_pass_from_validated_is_refused(
        self, api, validated_quarter
    ):
        """PRD: check 18 states "the validation pass accepts `DRAFT`", and the pass
        itself "moves `status` from `DRAFT` to `VALIDATED`". PRD: "`CENSUS_INCOMPLETE`,
        `severity` `WARNING`, one finding per calendar date from the period's
        `start_date` through `end_date` inclusive for which the submission has no census
        day at all, with `subject_ref` set to that date."

        Design: Corner/state_machines/validate_twice_second_call_rejected
        """
        scenario = validated_quarter
        universe = scenario.universe

        response = api.validate_submission(scenario.id, universe.coord_headers)
        validate_error(response, ApiErrorId.ERR_SUBMISSION_STATE_INVALID.value)

        data = scenario.refresh()
        assert data["status"] == SubmissionStatus.VALIDATED.value
        assert data["hprd_reported"] == approx_ratio(1.6000)

        rows, meta = validate_paginated(
            api.list_submission_findings(
                scenario.id,
                universe.coord_headers,
                {
                    "code": FindingCode.CENSUS_INCOMPLETE.value,
                    "status": FindingStatus.OPEN.value,
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 29
        subject_refs = sorted(row["subject_ref"] for row in rows)
        assert len(set(subject_refs)) == 29
        assert subject_refs[0] == "2026-04-02"
        assert subject_refs[-1] == "2026-04-30"

    def test_02_a_second_void_of_the_same_entry_is_refused_and_applies_nothing(
        self, api, client
    ):
        """PRD: "Voiding moves `entry_status` from `ACTIVE` to `VOID`, which is
        terminal, and requires the entry to be `ACTIVE`". PRD: check 19 is "The target
        `HourEntry` has `entry_status` `ACTIVE` — otherwise `ERR_HOUR_ENTRY_VOIDED`. This
        guards allocation replacement, voiding, and verification."

        Design: Corner/state_machines/void_hour_entry_twice_second_call_rejected
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        entry = scenario.capture_supported_hours()

        scenario.void_hours(entry["id"])
        after_void = validate_success(
            api.get_hour_entry(entry["id"], universe.coord_headers)
        )
        version_after_void = scenario.refresh()["version"]

        response = api.void_hour_entry(entry["id"], universe.coord_headers)
        validate_error(response, ApiErrorId.ERR_HOUR_ENTRY_VOIDED.value)

        stored = validate_success(
            api.get_hour_entry(entry["id"], universe.coord_headers)
        )
        assert stored["entry_status"] == EntryStatus.VOID.value
        assert stored["version"] == after_void["version"]

        data = scenario.refresh()
        assert data["version"] == version_after_void
        assert data["total_raw_hours"] == approx_hours(0.00)


class TestReEnterableStates:
    def test_01_a_disputed_census_day_is_corrected_and_reconciles_on_the_second_pass(
        self, api, draft_submission
    ):
        """PRD: "Because the counts can be corrected, a `DISPUTED` day is not stuck:
        correcting a count and reconciling again moves `DISPUTED` to `RECONCILED` once
        the variance falls to the tolerance or below, and resolves the outstanding
        `CENSUS_VARIANCE` finding for that date. There is no terminal census status."

        Design: Corner/state_machines/census_day_disputed_then_patched_and_reconciled_again
        """
        scenario = draft_submission
        universe = scenario.universe
        day = scenario.report_census("2026-04-01", 110, 100)
        disputed = scenario.reconcile_census(day["id"])
        assert disputed["status"] == CensusDayStatus.DISPUTED.value
        assert disputed["variance_pct"] == approx_ratio(0.1000)

        validate_success(
            api.update_census_day(
                day["id"], {"resident_count": 100}, universe.coord_headers
            )
        )
        reconciled = scenario.reconcile_census(day["id"])

        assert reconciled["resident_count"] == 100
        assert reconciled["variance_pct"] == approx_ratio(0.0000)
        assert reconciled["status"] == CensusDayStatus.RECONCILED.value

        rows, meta = validate_paginated(
            api.list_submission_findings(
                scenario.id,
                universe.coord_headers,
                {"code": FindingCode.CENSUS_VARIANCE.value, "limit": 100},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == FindingStatus.RESOLVED.value

        assert scenario.refresh()["total_resident_days"] == 100

    def test_02_an_unsupported_verdict_is_reversible_and_resolves_its_finding(
        self, api, client
    ):
        """PRD: "Recording `UNSUPPORTED` ... moves `verification_status` from
        `UNVERIFIED` to `UNSUPPORTED`, sets `verified_by_user_id` to the acting identity,
        creates a new `ValidationFinding` on the parent submission with `code`
        `UNSUPPORTED_HOURS`, `severity` `WARNING`, and `status` `OPEN`". PRD: recording
        `SUPPORTED` "moves `verification_status` to `SUPPORTED` from either `UNVERIFIED`
        or `UNSUPPORTED`, sets `verified_by_user_id` to the acting identity, resolves the
        `OPEN` `UNSUPPORTED_HOURS` finding previously raised for this entry".

        Design: Corner/state_machines/hour_entry_unsupported_then_supported_resolves_finding
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        entry = scenario.capture_supported_hours()
        scenario.report_census("2026-04-01", 5, 5)

        first = scenario.verify_hours(
            entry["id"], outcome=VerificationOutcome.UNSUPPORTED.value
        )
        assert first["verification_status"] == VerificationStatus.UNSUPPORTED.value
        assert first["verified_by_user_id"] == "auditor-verify-01"
        opened = find_finding(
            scenario.findings(), FindingCode.UNSUPPORTED_HOURS.value
        )
        assert opened is not None
        assert opened["status"] == FindingStatus.OPEN.value

        second = scenario.verify_hours(
            entry["id"],
            outcome=VerificationOutcome.SUPPORTED.value,
            user_id="auditor-verify-02",
        )
        assert second["verification_status"] == VerificationStatus.SUPPORTED.value
        assert second["verified_by_user_id"] == "auditor-verify-02"
        assert second["entry_status"] == EntryStatus.ACTIVE.value

        resolved = find_finding(
            scenario.findings(), FindingCode.UNSUPPORTED_HOURS.value
        )
        assert resolved is not None
        assert resolved["status"] == FindingStatus.RESOLVED.value
        assert scenario.refresh()["open_warning_finding_count"] == 0

    def test_03_a_rejected_batch_is_resubmitted_with_its_rejection_reason_cleared(
        self, api, universe
    ):
        """PRD: "Rejection is not the end: a rejected batch may be corrected and
        re-submitted, which clears `rejection_reason`, re-stamps `submitted_at`, and
        returns the batch to `SUBMITTED`, closing the cycle `DRAFT → SUBMITTED →
        REJECTED → SUBMITTED`."

        Design: Corner/state_machines/vendor_batch_reject_then_resubmit_clears_rejection_reason
        """
        vendor = VendorScenario(universe)
        vendor.file_batch([vendor.batch_line("2026-04-02")])
        vendor.submit_batch()

        rejected = vendor.reject_batch(BATCH_REJECTION_REASON)
        assert rejected["status"] == VendorSubmissionStatus.REJECTED.value
        assert rejected["rejection_reason"] == BATCH_REJECTION_REASON

        resubmitted = vendor.submit_batch()
        assert resubmitted["status"] == VendorSubmissionStatus.SUBMITTED.value
        assert resubmitted["rejection_reason"] is None
        assert_instant_equals(resubmitted["submitted_at"], DEFAULT_CLOCK, "submitted_at")
        assert resubmitted["accepted_direct_care_hours"] == approx_hours(0.00)

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"vendor_submission_id": vendor.batch["id"]}
            )
        )
        assert meta["total_count"] == 0


class TestMeasureDimensionsAreParallel:
    def test_01_the_audit_dimension_moves_while_publication_stands_still(
        self, api, client
    ):
        """PRD: "`StaffingMeasure` carries two independent state dimensions, and neither
        one moves the other." PRD: "From `UNDER_AUDIT` it moves to `AUDIT_CONFIRMED` when
        the case is dismissed, which leaves `measure_variant`, `total_nurse_hprd`,
        `rn_hprd`, and `staffing_rating` exactly as they were." PRD: "Throughout all of
        this, `publication_status` is untouched by audit transitions".

        Design: Corner/state_machines/staffing_measure_publication_and_audit_dimensions_move_independently
        """
        measure = build_published_measure(client)
        scenario = measure.scenario
        universe = scenario.universe

        case = CaseScenario(
            scenario,
            trigger_reason=CaseTriggerReason.PUBLIC_COMPLAINT.value,
            detail=CASE_DETAIL,
            staffing_measure_id=measure.id,
        )
        case.request_info("Provide the 2026-04-01 nurse assignment sheet.")
        case.respond("Assignment sheet attached; coverage as reported.")

        before = measure.refresh()
        assert before["publication_status"] == PublicationStatus.PUBLISHED.value
        assert before["audit_status"] == AuditStatus.UNDER_AUDIT.value

        closed = case.dismiss(CASE_DISMISSAL)
        assert closed["status"] == CaseStatus.DISMISSED.value

        after = measure.refresh()
        assert after["audit_status"] == AuditStatus.AUDIT_CONFIRMED.value
        assert after["publication_status"] == PublicationStatus.PUBLISHED.value
        assert after["measure_variant"] == MeasureVariant.AS_SUBMITTED.value
        assert after["total_nurse_hprd"] == approx_ratio(1.6000)

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.REPORTING_OPEN.value
        assert facility["substantiated_case_count"] == 0
