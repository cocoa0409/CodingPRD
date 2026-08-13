"""Engagement lifecycle: version contract, state gates, cycles, terminal lockdown."""
from test_helpers import (
    AUDITOR as AUDITOR_HEADERS,
    ApiErrorId,
    MANAGER,
    SPONSOR,
    TPA,
    add_participant,
    api_client,
    create_accepted_filing,
    create_engagement,
    create_engagement_in_report_issued,
    create_manual_finding,
    get_success_data,
    recompute_count,
    run_test,
    validate_error,
    validate_success,
)


class TestVersionContract:

    def test_version_increments_by_one_on_activate(self):
        """PRD §2.4: "`version` is a system-managed integer that increments by
        one on every modification."
        PRD §3.1: "Every one of these transitions increments the engagement's
        `version` by one."

        Design: Corner/entities/version_increments_on_mutation
        """
        eng = create_engagement()
        v0 = eng["version"]
        assert isinstance(v0, int)
        activated = validate_success(api_client.activate_engagement(eng["id"], SPONSOR))
        assert activated["version"] == v0 + 1, (
            f"activate must increment version by exactly 1: {v0} -> {activated['version']}"
        )
        assert activated["status"] == "DATA_COLLECTION"


class TestStateGates:

    def test_begin_fieldwork_without_participant_count_rejected(self):
        """PRD §3.1: "A `PlanAuditor` begins fieldwork, moving it from `TESTING`
        to `FIELDWORK` — but only once `participant_count_beginning` is non-null;
        if the participant count has never been computed, the transition is
        rejected with `ERR_PARTICIPANT_COUNT_REQUIRED` (HTTP 409)."

        Design: Corner/state_machines/begin_fieldwork_without_participant_count_rejected
        """
        eng = create_engagement()
        get_success_data(api_client.activate_engagement(eng["id"], SPONSOR))
        get_success_data(api_client.begin_testing(eng["id"], TPA))
        resp = api_client.begin_fieldwork(eng["id"], AUDITOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_COUNT_REQUIRED)
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["status"] == "TESTING"

    def test_issue_report_with_computed_test_result_rejected(self):
        """PRD §3.5: "An `issue_report` attempted while any current-official test
        result is still `COMPUTED` is rejected with `ERR_TEST_NOT_FINAL` (HTTP 409)."

        Design: Corner/state_machines/issue_report_with_computed_test_result_rejected
        """
        eng = create_engagement()
        # Both census groups populated so the ADP computation is meaningful.
        add_participant(eng["id"], "N-001", is_hce=False, deferral_amount_cy_cents=100_000,
                        compensation_cy_cents=5_000_000)
        add_participant(eng["id"], "H-001", is_hce=True, deferral_amount_cy_cents=100_000,
                        compensation_cy_cents=5_000_000)
        recompute_count(eng["id"])
        get_success_data(api_client.activate_engagement(eng["id"], SPONSOR))
        get_success_data(api_client.begin_testing(eng["id"], TPA))
        get_success_data(api_client.begin_fieldwork(eng["id"], AUDITOR_HEADERS))
        result = run_test(eng["id"], "ADP")
        assert result["status"] == "COMPUTED"
        resp = api_client.issue_report(eng["id"], AUDITOR_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TEST_NOT_FINAL)
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["status"] == "FIELDWORK"
        result_now = get_success_data(api_client.get_test_result(result["id"], SPONSOR))
        assert result_now["status"] == "COMPUTED"

    def test_late_deposit_scan_before_count_rejected(self):
        """PRD §3.4: "The scan requires that `remittance_standard_days` be
        non-null — that is, the participant count must have been computed first;
        otherwise it is rejected with `ERR_PARTICIPANT_COUNT_REQUIRED`."

        Design: Corner/state_machines/invalid_transition_scan_fresh_engagement_rejected
        """
        eng = create_engagement()
        participant = add_participant(eng["id"], "P-001", deferral_amount_cy_cents=100_000,
                                      compensation_cy_cents=5_000_000)
        get_success_data(api_client.create_contribution(
            {
                "engagement_id": eng["id"],
                "participant_id": participant["id"],
                "type": "ELECTIVE_DEFERRAL",
                "payroll_date": "2025-06-16",
                "deposit_date": "2025-06-30",
                "amount_cents": 100_000,
            },
            SPONSOR,
        ))
        resp = api_client.late_deposit_scan(eng["id"], TPA)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_COUNT_REQUIRED)


class TestReopenCycles:

    def test_engagement_reopen_cycles_and_version(self):
        """PRD §3.1: "Two cycle transitions allow the engagement to move backward:
        an `EngagementManager` may reopen data collection (`FIELDWORK` →
        `DATA_COLLECTION`) when new evidence arrives, and may reopen fieldwork
        (`REPORT_ISSUED` → `FIELDWORK`) when additional procedures are needed.
        Every one of these transitions increments the engagement's `version` by one."
        PRD §3.2: "it writes the resulting count into `participant_count_beginning`,
        derives `audit_required` and `required_schedule_type`, derives
        `remittance_standard_days`, and increments the engagement's `version` by one."

        Design: Corner/state_machines/engagement_reopen_cycles
        """
        eng = create_engagement()
        v0 = eng["version"]
        add_participant(eng["id"], "P-001")
        recompute_count(eng["id"])  # +1
        get_success_data(api_client.activate_engagement(eng["id"], SPONSOR))  # +1
        get_success_data(api_client.begin_testing(eng["id"], TPA))  # +1
        get_success_data(api_client.begin_fieldwork(eng["id"], AUDITOR_HEADERS))  # +1
        # First reopen loop: FIELDWORK -> DATA_COLLECTION -> TESTING -> FIELDWORK
        get_success_data(api_client.reopen_data_collection(eng["id"], MANAGER))  # +1
        get_success_data(api_client.begin_testing(eng["id"], TPA))  # +1
        get_success_data(api_client.begin_fieldwork(eng["id"], AUDITOR_HEADERS))  # +1
        get_success_data(api_client.issue_report(eng["id"], AUDITOR_HEADERS))  # +1
        # Second reopen loop: REPORT_ISSUED -> FIELDWORK -> REPORT_ISSUED
        get_success_data(api_client.reopen_fieldwork(eng["id"], MANAGER))  # +1
        final = get_success_data(api_client.issue_report(eng["id"], AUDITOR_HEADERS))  # +1
        assert final["status"] == "REPORT_ISSUED"
        assert final["version"] == v0 + 10, (
            f"10 version-bumping steps after creation: expected {v0 + 10}, "
            f"got {final['version']}"
        )


class TestCompletion:

    def test_complete_with_open_findings_rejected(self):
        """PRD §3.11: "First, the findings sweep: there must be no `AuditFinding`
        of the engagement in `OPEN`, `ACKNOWLEDGED`, `CORRECTION_IN_PROGRESS`, or
        `CORRECTED` status; the presence of any such finding is rejected with
        `ERR_OPEN_FINDINGS_REMAIN` (HTTP 409)."

        Design: Corner/state_machines/engagement_complete_with_open_findings_rejected
        """
        eng, _p = create_engagement_in_report_issued()
        finding = create_manual_finding(
            eng["id"], category="FILING_DEFECT", severity="LOW",
            description="typo on schedule")
        assert finding["status"] == "OPEN"
        resp = api_client.complete_engagement(eng["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_OPEN_FINDINGS_REMAIN)
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["status"] == "REPORT_ISSUED"
        finding_now = get_success_data(api_client.get_finding(finding["id"], SPONSOR))
        assert finding_now["status"] == "OPEN"

    def test_completed_engagement_rejects_further_transitions(self):
        """PRD §3.11: "The `COMPLETED` status is terminal for the engagement."
        PRD §3.1: "From `DRAFT`, a `SponsorAdmin` activates the engagement, moving
        it to `DATA_COLLECTION`."

        Design: Corner/state_machines/engagement_terminal_completed_lockdown
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_accepted_filing(eng["id"], schedule_type="I")
        assert filing["status"] == "ACCEPTED"
        completed = validate_success(api_client.complete_engagement(eng["id"], MANAGER))
        assert completed["status"] == "COMPLETED"
        resp = api_client.activate_engagement(eng["id"], SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["status"] == "COMPLETED"
