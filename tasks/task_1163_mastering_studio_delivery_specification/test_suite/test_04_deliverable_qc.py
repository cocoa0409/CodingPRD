"""Deliverable QC gates, rebuild cycle, loudness/true-peak boundaries, and
metadata format guards (PRD §3.7, §2.8, §2.5)."""
from test_helpers import (
    validate_success, validate_error, setup_project_approved,
    setup_ready_deliverable, make_deliverable, submit_deliverable_to_qc,
    record_qc_report, qc_pass_deliverable, make_engineer_headers,
    TEST_USERS, DEFAULT_UPC, DEFAULT_ISRC, ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]

QC_VERDICT_QUOTE = (
    "Passing a deliverable moves it `QC_PENDING → READY` and requires two things "
    "together: every QCReport row on the deliverable must have `passed` true, and "
    "the loudness-and-format compliance evaluation of §2.8 must pass — measured "
    "loudness within half an LU of target, true peak and loudness range at or under "
    "their ceilings, and an exact sample-rate and bit-depth match. A failure on "
    "either front is rejected with `ERR_QC_FAILED` (HTTP 422)."
)

REBUILD_QUOTE = (
    "Failing a deliverable moves it `QC_PENDING → QC_FAILED` when at least one "
    "report has `passed` false, and an engineer can then rebuild it, moving "
    "`QC_FAILED → BUILDING` for another attempt."
)


class TestDeliverableRebuildCycle:

    def test_qc_fail_moves_deliverable_to_qc_failed(self, api):
        """PRD §3.7: "%s"

        Design: Difficulty/non_linear_state_machine/deliverable_qc_failure_rebuild_cycle
        """ % REBUILD_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="TRUE_PEAK_IN_TOL",
                         passed=False, measured_value=0.5, tolerance=0.1)
        failed = validate_success(api.qc_fail_deliverable(deliverable["id"], TEST_USERS["qa_headers"]), 200)
        assert failed["status"] == "QC_FAILED"

    def test_rebuild_returns_failed_deliverable_to_building(self, api):
        """PRD §3.7: "%s"

        Design: Difficulty/non_linear_state_machine/deliverable_qc_failure_rebuild_cycle
        """ % REBUILD_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="TRUE_PEAK_IN_TOL",
                         passed=False, measured_value=0.5, tolerance=0.1)
        validate_success(api.qc_fail_deliverable(deliverable["id"], TEST_USERS["qa_headers"]), 200)
        rebuilt = validate_success(
            api.rebuild_deliverable(deliverable["id"],
                                    make_engineer_headers(ctx["engineer"]["id"])), 200)
        assert rebuilt["status"] == "BUILDING"


class TestDeliverableQcPassGatedByReports:

    def test_qc_pass_blocked_by_one_failing_report(self, api):
        """PRD §3.7: "%s"

        One passing and one failing QCReport: the verdict is rejected and the
        deliverable remains QC_PENDING.

        Design: Difficulty/cross_entity_state_dependency/deliverable_qc_pass_gated_by_qcreport_all_passed
        """ % QC_VERDICT_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="LOUDNESS_IN_TOL",
                         passed=True, measured_value=-14.0, tolerance=0.5)
        record_qc_report(deliverable["id"], check_code="CLIP_FREE",
                         passed=False, measured_value=1.0, tolerance=0.0)
        res = api.qc_pass_deliverable(deliverable["id"], TEST_USERS["qa_headers"])
        validate_error(res, ApiErrorId.ERR_QC_FAILED, expected_status=422)
        after = validate_success(api.get_deliverable(deliverable["id"], MANAGER), 200)
        assert after["status"] == "QC_PENDING"

    def test_qc_pass_succeeds_when_every_report_passed(self, api):
        """PRD §3.7: "%s"

        Design: Difficulty/cross_entity_state_dependency/deliverable_qc_pass_gated_by_qcreport_all_passed
        """ % QC_VERDICT_QUOTE
        ctx = setup_project_approved()
        ctx = setup_ready_deliverable(ctx)
        assert ctx["deliverable"]["status"] == "READY"


class TestTruePeakBoundary:

    def test_true_peak_at_exact_ceiling_passes(self, api):
        """PRD §2.8: "The measured `true_peak_dbtp` must not exceed the profile's
        `true_peak_dbtp` ceiling." PRD §3.7: "%s"

        A measured true peak exactly equal to the -1.0 dBTP ceiling does not exceed
        it, so the deliverable reaches READY.

        Design: Difficulty/boundary_precision_check/true_peak_at_ceiling_passes
        """ % QC_VERDICT_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx, true_peak_dbtp=-1.0)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="TRUE_PEAK_IN_TOL",
                         passed=True, measured_value=-1.0, tolerance=0.0)
        record_qc_report(deliverable["id"], check_code="LOUDNESS_IN_TOL",
                         passed=True, measured_value=-14.0, tolerance=0.5)
        ready = qc_pass_deliverable(deliverable["id"])
        assert ready["status"] == "READY"

    def test_true_peak_above_ceiling_rejected(self, api):
        """PRD §2.8: "The measured `true_peak_dbtp` must not exceed the profile's
        `true_peak_dbtp` ceiling." PRD §3.7: "%s"

        -0.9 dBTP exceeds the -1.0 dBTP ceiling, so the verdict is rejected.

        Design: Difficulty/boundary_precision_check/true_peak_at_ceiling_passes
        """ % QC_VERDICT_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx, true_peak_dbtp=-0.9)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="TRUE_PEAK_IN_TOL",
                         passed=False, measured_value=-0.9, tolerance=0.0)
        record_qc_report(deliverable["id"], check_code="LOUDNESS_IN_TOL",
                         passed=True, measured_value=-14.0, tolerance=0.5)
        res = api.qc_pass_deliverable(deliverable["id"], TEST_USERS["qa_headers"])
        validate_error(res, ApiErrorId.ERR_QC_FAILED, expected_status=422)


class TestLoudnessToleranceBoundary:

    def test_loudness_deviation_above_half_lu_fails(self, api):
        """PRD §2.8: "The measured `integrated_lufs` must sit within 0.5 LU of the
        profile's `integrated_lufs` — that is, the absolute difference between
        measured and target loudness must be no more than half an LU, with loudness
        comparisons carried at one decimal place." PRD §3.7: "%s"

        Measured -13.4 against a -14.0 target deviates by 0.6 LU and is rejected.

        Design: Corner/calculations/loudness_check_precision_half_lu_tolerance
        """ % QC_VERDICT_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx, integrated_lufs=-13.4)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="LOUDNESS_IN_TOL",
                         passed=False, measured_value=-13.4, tolerance=0.5)
        res = api.qc_pass_deliverable(deliverable["id"], TEST_USERS["qa_headers"])
        validate_error(res, ApiErrorId.ERR_QC_FAILED, expected_status=422)

    def test_loudness_deviation_at_exactly_half_lu_passes(self, api):
        """PRD §2.8: "The measured `integrated_lufs` must sit within 0.5 LU of the
        profile's `integrated_lufs` — that is, the absolute difference between
        measured and target loudness must be no more than half an LU, with loudness
        comparisons carried at one decimal place." PRD §3.7: "%s"

        Measured -13.5 against a -14.0 target deviates by exactly 0.5 LU and passes.

        Design: Corner/calculations/loudness_check_precision_half_lu_tolerance
        """ % QC_VERDICT_QUOTE
        ctx = setup_project_approved()
        deliverable = make_deliverable(ctx, integrated_lufs=-13.5)
        submit_deliverable_to_qc(ctx, deliverable["id"])
        record_qc_report(deliverable["id"], check_code="LOUDNESS_IN_TOL",
                         passed=True, measured_value=-13.5, tolerance=0.5)
        ready = qc_pass_deliverable(deliverable["id"])
        assert ready["status"] == "READY"


class TestMetadataFormatGuard:

    def test_embed_metadata_with_malformed_isrc_rejected(self, api):
        """PRD §3.7: "Malformed codes are rejected with `ERR_INVALID_FORMAT` (HTTP
        400), and when the parent project carries a `upc`, the tag's `upc` must equal
        it exactly, failing with `ERR_METADATA_MISMATCH` (HTTP 422) otherwise."
        PRD §2.5: "Twelfth (priority 12), code formats: ISRC and UPC values must
        match their format rules on project creation and on metadata embedding,
        failing with `ERR_INVALID_FORMAT` (HTTP 400)."

        The ISRC 'xxBAD' violates the 12-character format, so the format guard fires
        (400), never any fiscal check.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_approve
        """
        ctx = setup_project_approved()
        ctx = setup_ready_deliverable(ctx)
        res = api.embed_metadata(
            ctx["deliverable"]["id"], {"isrc": "xxBAD", "upc": DEFAULT_UPC},
            make_engineer_headers(ctx["engineer"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_FORMAT, expected_status=400)

    def test_embed_metadata_with_malformed_upc_rejected(self, api):
        """PRD §2.5: "Twelfth (priority 12), code formats: ISRC and UPC values must
        match their format rules on project creation and on metadata embedding,
        failing with `ERR_INVALID_FORMAT` (HTTP 400)." PRD §2.5: "Every request is
        evaluated against a fixed guard chain, and guards fire in ascending priority:
        a failure at an earlier step halts evaluation and masks every later check."

        A 5-digit UPC is malformed, so the format guard fires before the consistency
        guard at priority 13.

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_approve
        """
        ctx = setup_project_approved()
        ctx = setup_ready_deliverable(ctx)
        res = api.embed_metadata(
            ctx["deliverable"]["id"], {"isrc": DEFAULT_ISRC, "upc": "12345"},
            make_engineer_headers(ctx["engineer"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_FORMAT, expected_status=400)
