"""Filing deadlines, extensions, submission lateness/penalty, and amendments."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    SPONSOR,
    SYSTEM,
    TPA,
    ApiErrorId,
    add_participant,
    api_client,
    bulk_import,
    create_correction_program_filing_payload,
    create_engagement,
    create_engagement_in_report_issued,
    create_filing,
    create_filing_extension,
    create_filing_ready_to_file,
    create_small_plan_engagement,
    get_success_data,
    recompute_count,
    set_clock,
    validate_error,
    validate_success,
    walk_to_report_issued,
)


class TestDeadlineComputation:

    def test_weekend_roll_forward_on_due_dates(self):
        """PRD §3.9: "The raw `original_due_date` is the last day of the seventh
        month after the plan year ends; for a calendar plan year 2025, whose
        `plan_year_end` is `2026-01-01`, that raw date is `2026-07-31`. The raw
        date is then rolled forward over weekends: a raw date falling on a
        Saturday or Sunday moves to the following Monday (weekdays only, with no
        holiday calendar), producing the `original_due_date`."
        PRD §3.9: "A granted extension computes its `extended_due_date` as the
        15th day of the month three months after the month of the raw original due
        date, with the year rolling over if necessary, again weekend-rolled
        forward".

        Plan year ending 2025-06-30: raw due 2026-01-31 (Saturday) rolls to
        Monday 2026-02-02; extension raw 2026-04-15 (Wednesday) needs no roll.

        Design: Corner/calculations/filing_deadline_weekend_roll_forward
        """
        eng = create_engagement(plan_year_start="2024-07-01", plan_year_end="2025-07-01",
                                plan_name="FYE June Plan")
        add_participant(eng["id"], "P-001", eligibility_date="2024-01-01",
                        entry_date="2024-01-01")
        recompute_count(eng["id"])
        filing = create_filing(eng["id"])
        assert filing["original_due_date"] == "2026-02-02", (
            f"2026-01-31 is a Saturday; expected roll to Monday 2026-02-02, "
            f"got {filing['original_due_date']}"
        )
        assert filing["effective_due_date"] == "2026-02-02"
        # Form 5558 must be filed by the original deadline: move the logical
        # clock before 2026-02-02 (the server starts at 2026-08-01).
        set_clock("2025-12-15T00:00:00Z")
        extension = get_success_data(api_client.create_filing_extension(
            {"filing_id": filing["id"], "filed_date": "2025-12-15"}, TPA))
        assert extension["extended_due_date"] == "2026-04-15"
        assert extension["status"] == "GRANTED"
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["effective_due_date"] == "2026-04-15"
        assert filing_now["has_active_extension"] is True


class TestExtensions:

    def test_second_active_extension_rejected(self):
        """PRD §3.9: "There is one active extension per filing: creating an
        extension while an active (`GRANTED`) extension already exists is rejected
        with `ERR_EXTENSION_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/endpoints/second_active_extension_rejected
        """
        eng = create_engagement()
        filing = create_filing(eng["id"])
        set_clock("2026-07-01T00:00:00Z")
        first = create_filing_extension(filing["id"], filed_date="2026-07-01")
        assert first["status"] == "GRANTED"
        resp = api_client.create_filing_extension(
            {"filing_id": filing["id"], "filed_date": "2026-07-10"}, TPA)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_ALREADY_EXISTS)

    def test_extension_expires_via_clock(self):
        """PRD §2.10: "Advancing the clock re-evaluates time-driven rules: an
        extension whose `extended_due_date` has passed while its filing is not yet
        in `FILED` or `ACCEPTED` status transitions to `EXPIRED`, and the
        deadline-armern of the posture rule (§2.9) is re-evaluated."
        PRD §2.9: "the posture is `AT_RISK` when either ... (b) a filing exists
        whose logical clock date is later than its `effective_due_date` while its
        status is not `FILED` or `ACCEPTED`."

        Design: Corner/state_machines/extension_expires_via_clock
        """
        eng, _p = _small_plan()
        filing = create_filing(eng["id"])
        set_clock("2026-07-20T00:00:00Z")
        extension = create_filing_extension(filing["id"], filed_date="2026-07-20")
        assert extension["extended_due_date"] == "2026-10-15"
        assert extension["status"] == "GRANTED"
        set_clock("2026-10-16T00:00:00Z")
        extension_now = get_success_data(
            api_client.get_filing_extension(extension["id"], SPONSOR))
        assert extension_now["status"] == "EXPIRED"
        assert extension_now["extended_due_date"] == "2026-10-15"
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "AT_RISK"

    def test_submit_consumes_extension(self):
        """PRD §3.9: "The `effective_due_date` is the `extended_due_date` of the
        active extension in `GRANTED` or `USED` status, if one exists, and the
        `original_due_date` otherwise."
        PRD §3.9: "An active `GRANTED` extension moves to `USED`."

        Design: Corner/state_machines/extension_marked_used_on_submit
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        set_clock("2026-07-20T00:00:00Z")
        extension = create_filing_extension(filing["id"], filed_date="2026-07-20")
        assert extension["extended_due_date"] == "2026-10-15"
        set_clock("2026-09-01T00:00:00Z")
        submitted = validate_success(api_client.submit_filing(filing["id"], {}, MANAGER))
        assert submitted["status"] == "FILED"
        assert submitted["is_late"] is False
        assert submitted["filed_date"] == "2026-09-01"
        assert submitted["effective_due_date"] == "2026-10-15"
        extension_now = get_success_data(
            api_client.get_filing_extension(extension["id"], SPONSOR))
        assert extension_now["status"] == "USED"


class TestLateSubmission:

    def test_submit_after_deadline_without_flag_rejected(self):
        """PRD §3.9: "The logical clock date must be on or before the
        `effective_due_date`, unless the request sets `late_with_dfvcp` to true; a
        submission past the deadline without that flag is rejected with
        `ERR_FILING_DEADLINE_PASSED` (HTTP 409)."

        Design: Corner/endpoints/submit_after_deadline_without_dfvcp_flag_rejected
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        set_clock("2026-08-20T00:00:00Z")  # past the 2026-07-31 original due date
        resp = api_client.submit_filing(filing["id"], {}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "READY_TO_FILE"

    def test_dfvcp_late_submit_penalty_per_day(self):
        """PRD §3.9: "When the filing is late and was submitted with
        `late_with_dfvcp` true, the `penalty_cents` is computed under the DFVCP
        rule: the number of calendar days from the `effective_due_date` to the
        `filed_date` is multiplied by 1000 cents (ten dollars per day), and the
        result is capped — the cap is 75000 cents for a small plan (Schedule `I`)
        and 200000 cents for a large plan (Schedule `H`), and the penalty is the
        lesser of the raw figure and the cap, with the cap boundary-inclusive."

        Filed 2026-08-20 against a 2026-07-31 due date: 20 days x 1000c = 20000c.

        Design: Corner/calculations/dfvcp_penalty_per_day_and_cap
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        get_success_data(api_client.create_correction_program_filing(
            create_correction_program_filing_payload(eng["id"], program="DFVCP"),
            MANAGER))
        set_clock("2026-08-20T00:00:00Z")
        submitted = validate_success(api_client.submit_filing(
            filing["id"], {"late_with_dfvcp": True}, MANAGER))
        assert submitted["status"] == "FILED"
        assert submitted["is_late"] is True
        assert submitted["penalty_cents"] == 20_000
        assert submitted["filed_date"] == "2026-08-20"

    def test_filing_exactly_on_due_date_is_timely(self):
        """PRD §3.9: "`is_late` is computed as true when the `filed_date` is
        strictly later than the `effective_due_date` — filing exactly on the due
        date is timely."

        Design: Corner/calculations/dfvcp_penalty_per_day_and_cap
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        assert filing["original_due_date"] == "2026-07-31"
        set_clock("2026-07-31T00:00:00Z")
        submitted = validate_success(api_client.submit_filing(filing["id"], {}, MANAGER))
        assert submitted["status"] == "FILED"
        assert submitted["is_late"] is False
        assert submitted["penalty_cents"] == 0


class TestSubmitPreconditionOrdering:

    def _large_plan_ready_filing_without_report(self):
        """Audit-required engagement (100 participants, first-year plan) walked to
        REPORT_ISSUED WITHOUT the IQPA report attached; filing READY_TO_FILE."""
        eng = create_engagement(prior_year_schedule_type="NONE_FIRST_YEAR")
        bulk_import(eng["id"], 100, "KP")
        eng = recompute_count(eng["id"])
        assert eng["audit_required"] is True
        assert eng["required_schedule_type"] == "H"
        eng = walk_to_report_issued(eng["id"])
        filing = create_filing_ready_to_file(eng["id"], schedule_type="H")
        set_clock("2026-08-20T00:00:00Z")
        return eng, filing

    def test_missing_audit_report_beats_dfvcp_reference(self):
        """PRD §3.9: "Several preconditions guard the submit, and they are
        evaluated in the order given here. The engagement must be in
        `REPORT_ISSUED` status; otherwise the submit is rejected with
        `ERR_INVALID_STATE_TRANSITION`. When the engagement's `audit_required` is
        true, its `auditor_report_ref` must be non-null — the IQPA report must
        have been attached via the audit-report attachment step, which sets
        `auditor_report_ref` and increments the engagement's `version` — otherwise
        the submit is rejected with `ERR_AUDIT_REPORT_MISSING`."
        PRD §3.9: "Setting `late_with_dfvcp` to true in turn requires that a
        `CorrectionProgramFiling` with `program` `DFVCP` already exist for the
        engagement; without one the submit is rejected with
        `ERR_DFVCP_FILING_REQUIRED` (HTTP 422)."

        Both the audit-report check and the DFVCP-reference check fail here; the
        pinned evaluation order reports the audit report first.

        Design: Difficulty/priority_pair_validation_conflict/submit_missing_audit_report_beats_dfvcp_reference
        """
        _eng, filing = self._large_plan_ready_filing_without_report()
        resp = api_client.submit_filing(filing["id"], {"late_with_dfvcp": True}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_AUDIT_REPORT_MISSING)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "READY_TO_FILE"

    def test_dfvcp_flag_without_program_filing_rejected(self):
        """PRD §3.9: "Setting `late_with_dfvcp` to true in turn requires that a
        `CorrectionProgramFiling` with `program` `DFVCP` already exist for the
        engagement; without one the submit is rejected with
        `ERR_DFVCP_FILING_REQUIRED` (HTTP 422)."

        Same shape as the sibling test but with the IQPA report attached, so the
        DFVCP-reference check is the first (and only) failing guard.

        Design: Difficulty/priority_pair_validation_conflict/submit_missing_audit_report_beats_dfvcp_reference
        """
        eng, filing = self._large_plan_ready_filing_without_report()
        attached = get_success_data(api_client.attach_audit_report(
            eng["id"], {"auditor_report_ref": "iqpa-report-2025.pdf"},
            AUDITOR))
        assert attached["auditor_report_ref"] == "iqpa-report-2025.pdf"
        resp = api_client.submit_filing(filing["id"], {"late_with_dfvcp": True}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_DFVCP_FILING_REQUIRED, expected_status=422)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "READY_TO_FILE"


class TestRejectReopenAmendCycle:

    def _accepted_filing(self):
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        set_clock("2026-07-15T00:00:00Z")
        get_success_data(api_client.submit_filing(filing["id"], {}, MANAGER))
        accepted = get_success_data(api_client.record_disposition(
            filing["id"], {"outcome": "ACCEPTED"}, SYSTEM))
        return eng, accepted

    def test_reject_reopen_resubmit_cycle(self):
        """PRD §3.9: "A `REJECTED` filing returns to `DRAFT` for correction when a
        `TPASpecialist` reopens it."
        PRD §3.9: "After submission, the EFAST2 disposition is recorded by the
        `System` role with an `outcome` of `ACCEPTED` or `REJECTED` and an
        optional `rejection_reason`, moving the filing from `FILED` to `ACCEPTED`
        or `REJECTED` accordingly."

        Design: Difficulty/non_linear_state_machine/filing_reject_reopen_amend_cycle
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        assert filing["original_due_date"] == "2026-07-31"
        set_clock("2026-07-15T00:00:00Z")
        get_success_data(api_client.submit_filing(filing["id"], {}, MANAGER))
        rejected = get_success_data(api_client.record_disposition(
            filing["id"], {"outcome": "REJECTED", "rejection_reason": "EFAST2 schema error"},
            SYSTEM))
        assert rejected["status"] == "REJECTED"
        reopened = get_success_data(api_client.reopen_filing(filing["id"], TPA))
        assert reopened["status"] == "DRAFT"
        # Re-run the assembly steps and resubmit; the previously locked Schedule I
        # entry satisfies the verified-or-locked requirement.
        get_success_data(api_client.mark_schedules_complete(filing["id"], TPA))
        get_success_data(api_client.mark_ready(filing["id"], MANAGER))
        resubmitted = validate_success(api_client.submit_filing(filing["id"], {}, MANAGER))
        assert resubmitted["status"] == "FILED"
        assert resubmitted["is_late"] is False
        assert resubmitted["penalty_cents"] == 0
        accepted = get_success_data(api_client.record_disposition(
            filing["id"], {"outcome": "ACCEPTED"}, SYSTEM))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["is_amendment"] is False

    def test_amendment_cycle_marks_is_amendment(self):
        """PRD §3.9: "A successful amendment moves the filing to `AMENDED_DRAFT`
        and increments the filing's `version` by one. The amendment cycle then
        runs `AMENDED_DRAFT` → `SCHEDULES_COMPLETE` → `READY_TO_FILE` → `FILED` →
        `ACCEPTED`/`REJECTED`, with the same required-schedule rules applying to
        the mark-schedules-complete step from `AMENDED_DRAFT` as from `DRAFT`."
        PRD §3.9: "And `is_amendment` is set to true when the submission is made
        from an amendment cycle."

        Design: Difficulty/non_linear_state_machine/filing_reject_reopen_amend_cycle
        """
        _eng, accepted = self._accepted_filing()
        assert accepted["status"] == "ACCEPTED"
        current_version = accepted["version"]
        amended = validate_success(api_client.amend_filing(
            accepted["id"],
            {"expected_filing_version": current_version,
             "amendment_reason": "Schedule C omission"},
            TPA))
        assert amended["status"] == "AMENDED_DRAFT"
        assert amended["version"] == current_version + 1
        get_success_data(api_client.mark_schedules_complete(accepted["id"], TPA))
        get_success_data(api_client.mark_ready(accepted["id"], MANAGER))
        resubmitted = validate_success(api_client.submit_filing(accepted["id"], {}, MANAGER))
        assert resubmitted["status"] == "FILED"
        assert resubmitted["is_amendment"] is True
        assert resubmitted["is_late"] is False
        assert resubmitted["penalty_cents"] == 0
        final = get_success_data(api_client.record_disposition(
            accepted["id"], {"outcome": "ACCEPTED"}, SYSTEM))
        assert final["status"] == "ACCEPTED"


def _small_plan():
    return create_small_plan_engagement()
