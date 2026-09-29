"""Endpoint-level behaviour: what each declared operation writes, what it
leaves alone, and what it refuses."""

from test_helpers import (
    ApiErrorId,
    AppealGrounds,
    AuditReadinessVariant,
    CaseTriggerReason,
    CensusDayStatus,
    FindingCode,
    FindingSeverity,
    FindingStatus,
    HprdVariant,
    NON_EXISTENT_UUID,
    SubmissionStatus,
    TEST_DEFAULTS,
    VendorScenario,
    VendorSubmissionStatus,
    approx_hours,
    approx_ratio,
    approx_score,
    assert_audit_readiness_read,
    assert_hprd_read,
    build_draft_submission,
    build_published_measure,
    create_facility_payload,
    create_rating_appeal_payload,
    create_submission_payload,
    create_vendor_submission_payload,
    find_finding,
    make_state_auditor_headers,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_batch_line,
)
from test_helpers.constants import ACCEPTING_AUDITOR_USER_ID

REJECTION_REASON = "Census file does not tie to the MDS extract for the full month."
FINDING_AUDITOR_USER_ID = "auditor-find-01"
FIRST_WAIVER_NOTE = "Verified against the MDS extract."
SECOND_WAIVER_NOTE = "Waiving a second time."
OTHER_CASE_DETAIL = "Willow Bend census does not tie to the MDS extract."


class TestCensusCorrection:
    def test_01_a_correction_recomputes_the_variance_without_reconciling_the_day(
        self, api, validated_quarter
    ):
        """PRD: "A correction recomputes `variance_pct` whenever
        `mds_resident_count` is non-null after the change, re-runs the submission
        rollup, reverts a `VALIDATED` parent to `DRAFT`, and increments the
        submission's `version` by one, re-recording it on the day as
        `submission_version`." PRD: "`variance_pct` is the absolute difference between
        `resident_count` and `mds_resident_count`, divided by `mds_resident_count`,
        rounded half up to 4 decimal places." PRD: "A `variance_pct` of 0.0500 or less
        moves the day to `RECONCILED`; anything strictly greater moves it to
        `DISPUTED`."

        Design: Corner/endpoints/census_day_patch_updates_count_and_reverts_validated_parent
        """
        scenario = validated_quarter
        universe = scenario.universe
        day = scenario.census_days[0]
        version_before = scenario.refresh()["version"]
        assert scenario.submission["status"] == SubmissionStatus.VALIDATED.value

        corrected = validate_success(
            api.update_census_day(
                day["id"], {"resident_count": 4}, universe.coord_headers
            )
        )

        assert corrected["resident_count"] == 4
        assert corrected["mds_resident_count"] == 5
        assert corrected["variance_pct"] == approx_ratio(0.2000)
        assert corrected["status"] == CensusDayStatus.RECONCILED.value
        assert corrected["submission_version"] == version_before + 1

        reverted = scenario.refresh()
        assert reverted["status"] == SubmissionStatus.DRAFT.value
        assert reverted["total_resident_days"] == 4
        assert reverted["total_direct_care_hours"] == approx_hours(8.00)
        assert reverted["version"] == version_before + 1

        second_day = scenario.report_census("2026-04-02", 4, 5)
        disputed = scenario.reconcile_census(second_day["id"])
        assert disputed["status"] == CensusDayStatus.DISPUTED.value
        assert disputed["variance_pct"] == approx_ratio(0.2000)

        findings, _ = validate_paginated(
            api.list_submission_findings(
                scenario.id,
                universe.coord_headers,
                {
                    "code": FindingCode.CENSUS_VARIANCE.value,
                    "status": FindingStatus.OPEN.value,
                },
            )
        )
        raised = find_finding(
            findings, FindingCode.CENSUS_VARIANCE.value, "2026-04-02"
        )
        assert raised is not None
        assert raised["severity"] == FindingSeverity.WARNING.value


class TestRejectionAndFreeAmendment:
    def test_01_a_quarter_the_state_sent_back_is_corrected_free_of_charge(
        self, api, submitted_quarter
    ):
        """PRD: "**Rejection** requires the submission to be `SUBMITTED`, records the
        supplied `rejection_reason` and the acting identity as `accepted_by_user_id`,
        moves `status` to `REJECTED`, and increments `version` by one." PRD: "The base
        fee is 0 cents when the submission being reopened is in `REJECTED` — a quarter
        the state sent back is corrected free of charge". PRD: "the rate is 0.0300 when
        the base fee is at least 27500 cents, 0.0200 when it is at least 25000 cents,
        0.0100 when it is at least 1 cent, and 0.0000 when the base fee is 0."

        Design: Corner/endpoints/submission_reject_records_reason_and_reopen_from_rejected_is_free
        """
        scenario = submitted_quarter
        universe = scenario.universe

        rejected = scenario.reject(REJECTION_REASON)
        assert rejected["status"] == SubmissionStatus.REJECTED.value
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert rejected["accepted_by_user_id"] == ACCEPTING_AUDITOR_USER_ID

        reopened = scenario.reopen()
        assert reopened["status"] == SubmissionStatus.DRAFT.value
        assert reopened["amendment_index"] == 1
        assert reopened["amendment_surcharge_cents"] == 0
        assert reopened["waived_surcharge_cents"] == 0
        assert reopened["validated_by_worker_id"] is None
        assert reopened["attested_by_worker_id"] is None

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 0


class TestVendorBatchAcceptance:
    def test_01_one_out_of_period_line_stops_the_whole_synthesis(
        self, api, draft_submission
    ):
        """PRD: "Acceptance moves the batch to `ACCEPTED` and synthesizes one hour
        entry per element of `lines`, in `lines` order". PRD: "Because acceptance creates
        hours, the same per-line guards that police individual capture apply here too:
        `work_date` inside the period". PRD: "The target `VendorHourSubmission` is in a
        status the requested operation accepts — `DRAFT` or `REJECTED` for batch
        submission, `SUBMITTED` for batch acceptance and rejection, `ACCEPTED` for
        revocation — otherwise `ERR_VENDOR_SUBMISSION_STATE_INVALID`." PRD: "every line's
        worker must have `worker_type` `AGENCY_CONTRACTOR` with a `vendor_id` equal to
        the batch's `vendor_id` — a line naming an employee, an individual contractor, or
        another agency's contractor is refused with `ERR_VENDOR_WORKER_MISMATCH`."

        Design: Corner/endpoints/vendor_batch_accept_rejects_the_whole_batch_when_one_line_is_bad
        """
        scenario = draft_submission
        universe = scenario.universe
        vendor = VendorScenario(universe)
        vendor.file_batch(
            [vendor.batch_line("2026-04-06"), vendor.batch_line("2026-05-20")]
        )
        vendor.submit_batch()

        response = api.accept_vendor_submission(
            vendor.batch["id"], {"submission_id": scenario.id}, universe.coord_headers
        )
        validate_error(response, ApiErrorId.ERR_WORK_DATE_OUTSIDE_PERIOD.value)

        batch = vendor.refresh()
        assert batch["status"] == VendorSubmissionStatus.SUBMITTED.value
        assert batch["accepted_direct_care_hours"] == approx_hours(0.00)
        assert batch["accepted_hour_entry_ids"] == []

        _, meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers, {"vendor_submission_id": batch["id"]}
            )
        )
        assert meta["total_count"] == 0

        submission = scenario.refresh()
        assert submission["vendor_sourced_hours"] == approx_hours(0.00)
        assert submission["version"] == 1

        premature_revoke = api.revoke_vendor_submission(
            batch["id"], vendor.vendor_headers
        )
        validate_error(
            premature_revoke, ApiErrorId.ERR_VENDOR_SUBMISSION_STATE_INVALID.value
        )

        employee_batch = api.create_vendor_submission(
            create_vendor_submission_payload(
                vendor.vendor_id,
                universe.facility_id,
                universe.period_id,
                [
                    vendor_batch_line(
                        universe.w_rn["id"], universe.jc_rn["id"], "2026-04-06"
                    )
                ],
            ),
            vendor.vendor_headers,
        )
        validate_error(employee_batch, ApiErrorId.ERR_VENDOR_WORKER_MISMATCH.value)


class TestAppealCaseLinkage:
    def test_01_a_contested_case_must_belong_to_the_appealing_facility(
        self, api, client, case_auditor_headers
    ):
        """PRD: filing "requires any named contested case to belong to the same facility
        as the appealed measure (`ERR_APPEAL_CASE_MISMATCH`)." PRD: "The appeal copies
        `facility_id` from the appealed measure ... sets the appealed measure's
        `has_open_appeal` to true, and increments that measure's `version` by one."

        Design: Corner/endpoints/appeal_naming_another_facilitys_case_is_rejected
        """
        measure = build_published_measure(client)
        universe = measure.universe
        version_before = measure.refresh()["version"]

        other_facility = validate_success(
            api.create_facility(
                create_facility_payload(
                    ccn=TEST_DEFAULTS["SECOND_FACILITY_CCN"],
                    name=TEST_DEFAULTS["SECOND_FACILITY_NAME"],
                    certified_bed_count=TEST_DEFAULTS["SECOND_FACILITY_BED_COUNT"],
                ),
                universe.admin_headers,
            ),
            expected_status=201,
        )
        other_submission = validate_success(
            api.create_submission(
                create_submission_payload(other_facility["id"], universe.period_id),
                universe.admin_headers,
            ),
            expected_status=201,
        )
        other_case = validate_success(
            api.create_discrepancy_case(
                {
                    "facility_id": other_facility["id"],
                    "submission_id": other_submission["id"],
                    "trigger_reason": CaseTriggerReason.CENSUS_MISMATCH.value,
                    "detail": OTHER_CASE_DETAIL,
                },
                case_auditor_headers,
            ),
            expected_status=201,
        )

        response = api.create_rating_appeal(
            create_rating_appeal_payload(
                measure.id,
                version_before,
                grounds=AppealGrounds.CENSUS_ERROR.value,
                narrative="Appealing on the strength of another facility's case.",
                discrepancy_case_id=other_case["id"],
            ),
            universe.fac_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_CASE_MISMATCH.value)

        assert other_case["facility_id"] == other_facility["id"]
        data = measure.refresh()
        assert data["facility_id"] == universe.facility_id
        assert data["has_open_appeal"] is False
        assert data["version"] == version_before

        _, meta = validate_paginated(
            api.list_rating_appeals(
                universe.fac_admin_headers,
                {"discrepancy_case_id": other_case["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestComputedReadsPersistNothing:
    def test_01_neither_computed_read_moves_the_stored_score_or_version(
        self, api, accepted_quarter
    ):
        """PRD: `GET /facilities/{id}/audit-readiness` "runs
        calculations.audit_support_score for one submission of this facility under the
        selected variant without persisting anything." PRD: `GET /submissions/{id}/hprd`
        "runs calculations.hprd_reconciliation for the submission under the selected
        variant without persisting anything." PRD: "Under the **audit-adjusted** reading,
        the numerator population is narrowed to active entries whose
        `verification_status` is `SUPPORTED` ... and each counted census day contributes
        its `mds_resident_count` when that is non-null and its `resident_count`
        otherwise."

        Design: Corner/endpoints/audit_readiness_and_hprd_reads_are_side_effect_free
        """
        scenario = accepted_quarter
        universe = scenario.universe
        version_before = scenario.refresh()["version"]

        readiness = validate_success(
            api.get_audit_readiness(
                universe.facility_id,
                universe.coord_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.FULL.value,
                },
            )
        )
        assert_audit_readiness_read(readiness, AuditReadinessVariant.FULL.value)
        assert readiness["considered_entry_count"] == 1
        assert readiness["considered_hours"] == approx_hours(8.00)
        assert readiness["supported_hours"] == approx_hours(8.00)
        assert readiness["support_ratio"] == approx_ratio(1.0000)
        assert readiness["vendor_attestation_ratio"] == approx_ratio(1.0000)
        assert readiness["census_reconciled_ratio"] == approx_ratio(1.0000)
        assert readiness["score"] == approx_score(100.00)
        assert readiness["at_risk"] is False

        hprd = validate_success(
            api.get_submission_hprd(
                scenario.id,
                universe.coord_headers,
                {"variant": HprdVariant.AUDIT_ADJUSTED.value},
            )
        )
        assert_hprd_read(hprd, HprdVariant.AUDIT_ADJUSTED.value)
        assert hprd["total_direct_care_hours"] == approx_hours(8.00)
        assert hprd["resident_days"] == 5
        assert hprd["total_nurse_hprd"] == approx_ratio(1.6000)
        assert hprd["rn_hprd"] == approx_ratio(1.6000)
        assert hprd["implausible"] is False
        assert hprd["weekend_direct_care_hours"] == approx_hours(0.00)
        assert hprd["weekend_resident_days"] == 0
        assert hprd["weekend_total_nurse_hprd"] is None

        after = scenario.refresh()
        assert after["audit_support_score"] == approx_score(100.00)
        assert after["version"] == version_before


class TestFindingWaiverGuards:
    def test_01_a_waived_finding_and_an_unknown_finding_fail_differently(
        self, api, client
    ):
        """PRD: "Waiving requires the finding's `status` to be `OPEN`
        (`ERR_FINDING_NOT_OPEN`), moves `status` to `WAIVED`, records
        `waived_by_user_id` from the acting identity, stamps `resolved_at`, appends the
        `waiver_note` to the finding's `detail`". PRD: "only once the submission resolves
        is the finding looked up, and a finding that does not exist — or exists but does
        not belong to the named submission — is rejected with `ERR_FINDING_NOT_FOUND`."

        Design: Corner/endpoints/waive_rejected_when_finding_already_waived_or_unknown
        """
        scenario = build_draft_submission(client)
        scenario.capture_hours(
            work_date="2026-04-01", shift_start="00:00", shift_end="16:00"
        )
        scenario.report_census("2026-04-01", 1, 1)
        scenario.validate()

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
        finding_id = findings[0]["id"]

        waived = scenario.waive(
            finding_id, FIRST_WAIVER_NOTE, user_id=FINDING_AUDITOR_USER_ID
        )
        assert waived["status"] == FindingStatus.WAIVED.value
        version_before = scenario.refresh()["version"]

        second_waiver = api.waive_finding(
            scenario.id,
            finding_id,
            {"waiver_note": SECOND_WAIVER_NOTE},
            auditor_headers,
        )
        validate_error(second_waiver, ApiErrorId.ERR_FINDING_NOT_OPEN.value)

        unknown_finding = api.waive_finding(
            scenario.id,
            NON_EXISTENT_UUID,
            {"waiver_note": "Waiving a finding that does not exist."},
            auditor_headers,
        )
        validate_error(unknown_finding, ApiErrorId.ERR_FINDING_NOT_FOUND.value)

        stored = validate_success(
            api.get_validation_finding(finding_id, auditor_headers)
        )
        assert stored["status"] == FindingStatus.WAIVED.value
        assert FIRST_WAIVER_NOTE in stored["detail"]
        assert SECOND_WAIVER_NOTE not in stored["detail"]

        after = scenario.refresh()
        assert after["open_fatal_finding_count"] == 0
        assert after["version"] == version_before
