"""Audit execution lifecycle: start/submit/decide cycles and interview evidence."""
from test_helpers import (
    OFFICER,
    ApiErrorId,
    assert_worker_interview_record,
    decide_audit,
    file_grievance,
    make_auditor_headers,
    record_interviews,
    setup_in_progress_audit,
    setup_report_submitted_audit,
    setup_completed_audit,
    submit_report,
    triage_grievance,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReturnForCorrectionCycle:
    def test_audit_report_return_for_correction_cycle(self, api):
        """PRD §3.3: "A `RETURN_FOR_CORRECTION` decision instead moves the audit
        `REPORT_SUBMITTED → IN_PROGRESS`, reopening the report cycle; the
        existing worker interview record is retained, an optional
        `correction_note` may accompany the return, and this loop may repeat as
        often as needed."
        PRD §3.3: "A `COMPLETE` decision moves the audit `REPORT_SUBMITTED →
        COMPLETED`"

        Design: Difficulty/non_linear_state_machine/audit_report_return_correction_cycle
        """
        ctx = setup_report_submitted_audit(
            supplier_name="Echo Electronics", sector="ELECTRONICS",
            facility_name="Austin Assembly", with_verifier=False,
        )
        audit_id = ctx["audit"]["id"]
        assert ctx["audit"]["status"] == "REPORT_SUBMITTED"

        returned = decide_audit(
            audit_id, "RETURN_FOR_CORRECTION",
            correction_note="Expand scope of wage sampling",
        )
        assert returned["status"] == "IN_PROGRESS", "cycle edge reopens fieldwork"

        resubmitted = submit_report(audit_id, ctx["auditor"]["id"])
        assert resubmitted["status"] == "REPORT_SUBMITTED", (
            "the second submit succeeds on the same audit"
        )

        completed = decide_audit(audit_id, "COMPLETE")
        assert completed["status"] == "COMPLETED"

    def test_audit_version_increments_across_correction_cycle(self, api):
        """PRD §2.4: "Mutable resources additionally carry `updated_at`, an ISO
        8601 UTC timestamp with three fractional digits refreshed on every
        change, and `version`, a system-managed integer that increments by one
        on every mutation"
        PRD §3.3: "reopening the report cycle; the existing worker interview
        record is retained"

        Design: Difficulty/non_linear_state_machine/audit_report_return_correction_cycle
        """
        ctx = setup_report_submitted_audit(
            supplier_name="Echo Electronics", sector="ELECTRONICS",
            facility_name="Austin Assembly", with_verifier=False,
        )
        audit_id = ctx["audit"]["id"]
        v_at_submit = ctx["audit"]["version"]

        decide_audit(audit_id, "RETURN_FOR_CORRECTION",
                     correction_note="Expand scope of wage sampling")
        submit_report(audit_id, ctx["auditor"]["id"])
        completed = decide_audit(audit_id, "COMPLETE")

        # return, resubmit, complete: three further audit mutations.
        assert completed["version"] == v_at_submit + 3, (
            "every mutation increments the audit version by exactly one"
        )
        records, _ = validate_paginated(
            api.list_worker_interview_records(audit_id, OFFICER)
        )
        assert len(records) == 1, (
            "the interview record is retained across the correction cycle"
        )
        assert records[0]["id"] == ctx["interview_record"]["id"]


class TestAuditStateLockdowns:
    def test_audit_start_from_report_submitted_rejected(self, api):
        """PRD §3.3: "Starting requires the audit to be `SCHEDULED`
        (`ERR_AUDIT_INVALID_STATE`)"

        Design: Corner/state_machines/audit_start_from_report_submitted_rejected
        """
        ctx = setup_report_submitted_audit(supplier_name="Alfa Goods",
                                           facility_name="Site U",
                                           with_verifier=False)
        audit = ctx["audit"]
        assert audit["status"] == "REPORT_SUBMITTED"
        resp = api.start_audit(
            audit["id"], make_auditor_headers(ctx["auditor"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_INVALID_STATE, 409)
        reread = validate_success(api.get_audit(audit["id"], OFFICER))
        assert reread["status"] == "REPORT_SUBMITTED"

    def test_audit_submit_after_completed_rejected(self, api):
        """PRD §3.3: "Submission requires the audit to be `IN_PROGRESS`
        (`ERR_AUDIT_INVALID_STATE`)"
        PRD §3.2: "Once any audit of the facility reaches a terminal state —
        `COMPLETED` or `FAILED_ZT`"

        Design: Corner/state_machines/audit_submit_after_complete_terminal_lockdown
        """
        ctx = setup_completed_audit(supplier_name="Bravo Goods",
                                    facility_name="Site T",
                                    with_verifier=False)
        audit = ctx["audit"]
        assert audit["status"] == "COMPLETED"
        resp = api.submit_audit_report(
            audit["id"], make_auditor_headers(ctx["auditor"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_INVALID_STATE, 409)
        reread = validate_success(api.get_audit(audit["id"], OFFICER))
        assert reread["status"] == "COMPLETED", "COMPLETED is terminal"

    def test_submit_report_without_interviews_rejected(self, api):
        """PRD §3.3: "Submission requires the audit to be `IN_PROGRESS`
        (`ERR_AUDIT_INVALID_STATE`), the same ownership rule as starting, and
        the audit's single worker interview record to already exist
        (`ERR_INTERVIEW_RECORD_MISSING`)."

        Design: Corner/validations/submit_without_interview_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="Foxtrot C",
                                      facility_name="Site S2",
                                      with_verifier=False)
        resp = api.submit_audit_report(
            ctx["audit"]["id"], make_auditor_headers(ctx["auditor"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_RECORD_MISSING, 409)
        reread = validate_success(api.get_audit(ctx["audit"]["id"], OFFICER))
        assert reread["status"] == "IN_PROGRESS"


class TestInterviewSampleMinimum:
    def test_interview_sample_below_minimum_rejected(self, api):
        """PRD §3.7: "The minimum sample scales with the site:
        `interview_count` must be at least the square root of the facility's
        `worker_count` rounded up to a whole number, or the record is rejected
        with `ERR_INTERVIEW_SAMPLE_TOO_SMALL` (422) — a facility of 100 workers
        requires exactly 10 interviews, 99 workers still require 10, and 101
        workers require 11."

        Design: Difficulty/boundary_precision_check/interview_sample_exact_minimum
        """
        ctx = setup_in_progress_audit(supplier_name="Lima Parts",
                                      sector="HARDLINES", worker_count=100,
                                      facility_name="Tulsa Works",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        lead = make_auditor_headers(ctx["auditor"]["id"])
        # 9 < ceil(sqrt(100)) == 10: rejected.
        resp = api.create_worker_interview_record(
            audit_id,
            {"interview_count": 9, "forced_labor_indicators": False,
             "recruitment_fee_indicators": False},
            lead,
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_SAMPLE_TOO_SMALL, 422)
        # Exactly the minimum passes.
        record = validate_success(
            api.create_worker_interview_record(
                audit_id,
                {"interview_count": 10, "forced_labor_indicators": False,
                 "recruitment_fee_indicators": False},
                lead,
            ),
            201,
        )
        assert_worker_interview_record(record)
        assert record["interview_count"] == 10

    def test_interview_rejected_attempt_leaves_no_record(self, api):
        """PRD §3.7: "the record's `audit_id` ties it there, just as the fee
        review of §3.8 stores its own `audit_id` — and exactly one such record
        may exist per audit: a second attempt is rejected with
        `ERR_RECORD_ALREADY_EXISTS`."
        PRD §3.7: "`interview_count` must be at least the square root of the
        facility's `worker_count` rounded up to a whole number, or the record is
        rejected with `ERR_INTERVIEW_SAMPLE_TOO_SMALL` (422)"

        Design: Difficulty/boundary_precision_check/interview_sample_exact_minimum
        """
        ctx = setup_in_progress_audit(supplier_name="Lima Parts",
                                      sector="HARDLINES", worker_count=100,
                                      facility_name="Tulsa Works",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        lead = make_auditor_headers(ctx["auditor"]["id"])
        validate_error(
            api.create_worker_interview_record(
                audit_id,
                {"interview_count": 9, "forced_labor_indicators": False,
                 "recruitment_fee_indicators": False},
                lead,
            ),
            ApiErrorId.ERR_INTERVIEW_SAMPLE_TOO_SMALL,
        )
        record = validate_success(
            api.create_worker_interview_record(
                audit_id,
                {"interview_count": 10, "forced_labor_indicators": False,
                 "recruitment_fee_indicators": False},
                lead,
            ),
            201,
        )
        records, meta = validate_paginated(
            api.list_worker_interview_records(audit_id, OFFICER)
        )
        assert meta["total_count"] == 1 and len(records) == 1, (
            "the rejected attempt left no residue on the one-record slot"
        )
        assert records[0]["id"] == record["id"]
        assert records[0]["interview_count"] == 10

    def test_interview_min_sample_non_square_workers(self, api):
        """PRD §3.7: "`interview_count` must be at least the square root of the
        facility's `worker_count` rounded up to a whole number, or the record is
        rejected with `ERR_INTERVIEW_SAMPLE_TOO_SMALL` (422)"

        Design: Corner/calculations/interview_min_sample_non_square
        """
        ctx = setup_in_progress_audit(supplier_name="Lima Goods",
                                      sector="HARDLINES", worker_count=255,
                                      facility_name="Site K",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        lead = make_auditor_headers(ctx["auditor"]["id"])
        # ceil(sqrt(255)) == 16: 15 fails, 16 passes.
        resp = api.create_worker_interview_record(
            audit_id,
            {"interview_count": 15, "forced_labor_indicators": False,
             "recruitment_fee_indicators": False},
            lead,
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_SAMPLE_TOO_SMALL, 422)
        record = validate_success(
            api.create_worker_interview_record(
                audit_id,
                {"interview_count": 16, "forced_labor_indicators": False,
                 "recruitment_fee_indicators": False},
                lead,
            ),
            201,
        )
        assert record["interview_count"] == 16

    def test_interview_record_is_immutable_registration_record(self, api):
        """PRD §2.4: "Two registration records are immutable after creation and
        therefore carry only `id` and `created_at`: the CodeAcknowledgment and
        the WorkerInterviewRecord. On both, `updated_at` and `version` are
        absent."
        PRD §3.7: "The record carries the `interview_count`, the booleans
        `forced_labor_indicators` and `recruitment_fee_indicators` reporting
        what the interviews surfaced, and optional anonymized `notes`."

        Design: Corner/entities/worker_interview_record_common_fields_light
        """
        ctx = setup_in_progress_audit(supplier_name="Yankee Parts",
                                      sector="HARDLINES", facility_name="Site W",
                                      with_verifier=False)
        record = record_interviews(
            ctx["audit"]["id"], ctx["auditor"]["id"], interview_count=4,
            forced_labor_indicators=True, notes="Two workers mentioned deductions",
        )
        assert_worker_interview_record(record)
        assert record["interview_count"] == 4
        assert record["forced_labor_indicators"] is True
        assert record["recruitment_fee_indicators"] is False

    def test_duplicate_interview_record_rejected(self, api):
        """PRD §3.7: "exactly one such record may exist per audit: a second
        attempt is rejected with `ERR_RECORD_ALREADY_EXISTS`."

        Design: Corner/validations/duplicate_interview_record_rejected
        """
        ctx = setup_in_progress_audit(supplier_name="Victor A", sector="FOOD",
                                      facility_name="Site C",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        lead = make_auditor_headers(ctx["auditor"]["id"])
        first = record_interviews(audit_id, ctx["auditor"]["id"],
                                  interview_count=4)
        resp = api.create_worker_interview_record(
            audit_id,
            {"interview_count": 6, "forced_labor_indicators": True,
             "recruitment_fee_indicators": True},
            lead,
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_ALREADY_EXISTS, 409)
        records, _ = validate_paginated(
            api.list_worker_interview_records(audit_id, OFFICER)
        )
        assert len(records) == 1
        assert records[0]["id"] == first["id"]
        assert records[0]["interview_count"] == 4, "the first record is unchanged"


class TestCompletionGate:
    def test_critical_grievance_blocks_audit_completion(self, api):
        """PRD §3.3: "A `COMPLETE` decision moves the audit `REPORT_SUBMITTED →
        COMPLETED`; it is refused while any grievance at the audit's facility
        has severity `CRITICAL` and a status of `SUBMITTED`, `UNDER_REVIEW`, or
        `ESCALATED` (`ERR_CRITICAL_GRIEVANCE_UNRESOLVED`)."

        Design: Corner/validations/critical_grievance_blocks_audit_completion
        """
        ctx = setup_report_submitted_audit(supplier_name="Alfa C", sector="FOOD",
                                           facility_name="Site X2",
                                           with_verifier=False)
        audit_id = ctx["audit"]["id"]
        grievance = file_grievance(
            ctx["facility"]["id"], channel="AUDIT_INTERVIEW", category="SAFETY",
            severity="CRITICAL", description="Fire exits locked",
        )
        blocked = api.decide_audit(audit_id, {"decision": "COMPLETE"}, OFFICER)
        validate_error(blocked, ApiErrorId.ERR_CRITICAL_GRIEVANCE_UNRESOLVED, 409)

        triage_grievance(grievance["id"], "START_REVIEW")
        triage_grievance(grievance["id"], "RESOLVE",
                         resolution_note="Exits unlocked, verified")
        completed = decide_audit(audit_id, "COMPLETE")
        assert completed["status"] == "COMPLETED", (
            "resolving the critical grievance unblocks completion"
        )
