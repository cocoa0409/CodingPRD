"""Filing assembly: schedules, service-provider fees, readiness gates, OCC."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    SPONSOR,
    SYSTEM,
    TPA,
    ApiErrorId,
    api_client,
    create_engagement,
    create_engagement_in_report_issued,
    create_filing,
    create_filing_ready_to_file,
    create_manual_finding,
    create_schedule_entry_payload,
    create_service_provider_fee_payload,
    create_small_plan_engagement,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)


class TestScheduleCFeeAggregation:

    def test_fee_threshold_boundary_and_eligible_indirect_exclusion(self):
        """PRD §3.8: "The aggregation groups all of the engagement's fees by
        exact `provider_name` string match; for each provider, the reportable
        total is the sum of `amount_cents` over the rows whose `compensation_type`
        is `DIRECT` or `INDIRECT`, and `ELIGIBLE_INDIRECT` amounts are excluded
        from the threshold test as memo-only. A provider is reportable when that
        total is at least 500000 cents (that is, five thousand dollars) — the
        comparison is boundary-inclusive."
        PRD §3.8: "this upserts one `DRAFT` `ScheduleEntry` of `schedule_type` `C`
        per reportable provider onto the filing, with a `line_item` naming the
        provider, and returns a summary containing the `reportable_provider_count`,
        the `reportable_total_cents`, and the list of `schedule_entry_ids` it wrote."

        Design: Corner/calculations/schedule_c_fee_threshold_exactly_5000
        """
        eng, _p = create_small_plan_engagement()
        filing = create_filing(eng["id"])
        fee_a1 = get_success_data(api_client.create_service_provider_fee(
            create_service_provider_fee_payload(
                eng["id"], "Alpha Recordkeepers", service_code="RECORDKEEPING",
                compensation_type="DIRECT", amount_cents=300_000), SPONSOR))
        get_success_data(api_client.create_service_provider_fee(
            create_service_provider_fee_payload(
                eng["id"], "Alpha Recordkeepers", service_code="TPA",
                compensation_type="INDIRECT", amount_cents=200_000), SPONSOR))
        fee_b = get_success_data(api_client.create_service_provider_fee(
            create_service_provider_fee_payload(
                eng["id"], "Beta Advisors", service_code="CONSULTING",
                compensation_type="DIRECT", amount_cents=499_999), SPONSOR))
        fee_g = get_success_data(api_client.create_service_provider_fee(
            create_service_provider_fee_payload(
                eng["id"], "Gamma Brokers", service_code="INVESTMENT_MANAGEMENT",
                compensation_type="ELIGIBLE_INDIRECT", amount_cents=600_000), SPONSOR))
        fee_a1_now = get_success_data(api_client.get_service_provider_fee(fee_a1["id"], SPONSOR))
        assert fee_a1_now["reportable_on_schedule_c"] is True, (
            "Alpha direct+indirect = 500000, exactly at the boundary-inclusive threshold"
        )
        fee_b_now = get_success_data(api_client.get_service_provider_fee(fee_b["id"], SPONSOR))
        assert fee_b_now["reportable_on_schedule_c"] is False, "499999 is below threshold"
        fee_g_now = get_success_data(api_client.get_service_provider_fee(fee_g["id"], SPONSOR))
        assert fee_g_now["reportable_on_schedule_c"] is False, (
            "ELIGIBLE_INDIRECT amounts are memo-only and excluded from the threshold"
        )
        summary = get_success_data(api_client.compute_fee_disclosure(
            eng["id"], {"filing_id": filing["id"]}, TPA))
        assert summary["reportable_provider_count"] == 1
        assert summary["reportable_total_cents"] == 500_000


class TestFilingUniqueness:

    def test_second_filing_per_engagement_rejected(self):
        """PRD §3.8: "there is at most one filing per engagement ever, and
        creating a second is rejected with `ERR_FILING_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_filing_per_engagement_rejected
        """
        eng = create_engagement()
        first = create_filing(eng["id"])
        assert first["status"] == "DRAFT"
        resp = api_client.create_filing({"engagement_id": eng["id"]}, TPA)
        validate_error(resp, ApiErrorId.ERR_FILING_ALREADY_EXISTS)


class TestScheduleEntries:

    def test_verified_entry_locks_on_submit(self):
        """PRD §3.8: "A `PlanAuditor` verifies each schedule entry, moving it from
        `DRAFT` to `VERIFIED`."
        PRD §3.9: "Submission also locks the schedules: every `VERIFIED` schedule
        entry of the filing moves to `LOCKED`."

        Design: Corner/endpoints/schedule_entry_verify_and_lock_on_submit
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing(eng["id"])
        entry = get_success_data(api_client.create_schedule_entry(
            create_schedule_entry_payload(filing["id"], schedule_type="I"), TPA))
        assert entry["status"] == "DRAFT"
        verified = get_success_data(api_client.verify_schedule_entry(entry["id"], AUDITOR))
        assert verified["status"] == "VERIFIED"
        get_success_data(api_client.mark_schedules_complete(filing["id"], TPA))
        get_success_data(api_client.mark_ready(filing["id"], MANAGER))
        set_clock("2026-07-15T00:00:00Z")
        submitted = validate_success(api_client.submit_filing(filing["id"], {}, MANAGER))
        assert submitted["status"] == "FILED"
        entry_now = get_success_data(api_client.get_schedule_entry(entry["id"], SPONSOR))
        assert entry_now["status"] == "LOCKED"

    def test_schedule_c_foreign_fee_reference_rejected(self):
        """PRD §3.8: "for a Schedule C entry the payload carries
        `service_provider_fee_ids`, an array of `ServiceProviderFee` ids that must
        all belong to the filing's engagement — a reference to a fee of a
        different engagement is rejected with `ERR_FOREIGN_REFERENCE` (HTTP 422)."

        Design: Corner/endpoints/schedule_c_entry_foreign_fee_reference_rejected
        """
        eng_a = create_engagement(plan_name="ForeignRef Plan A")
        eng_b = create_engagement(plan_name="ForeignRef Plan B")
        filing = create_filing(eng_a["id"])
        fee_b = get_success_data(api_client.create_service_provider_fee(
            create_service_provider_fee_payload(
                eng_b["id"], "Beta Advisors", service_code="CONSULTING",
                compensation_type="DIRECT", amount_cents=600_000), SPONSOR))
        resp = api_client.create_schedule_entry(
            create_schedule_entry_payload(
                filing["id"], schedule_type="C", line_item="C-1c Beta Advisors",
                amount_cents=600_000,
                payload={"service_provider_fee_ids": [fee_b["id"]]}),
            TPA)
        validate_error(resp, ApiErrorId.ERR_FOREIGN_REFERENCE, expected_status=422)


class TestReadinessGate:

    def test_mark_ready_blocked_engagement_rejected(self):
        """PRD §3.8: "The engagement's `posture` must not be `BLOCKED`; a
        readiness attempt against a `BLOCKED` engagement is rejected with
        `ERR_ENGAGEMENT_BLOCKED` (HTTP 409)."
        PRD §2.9: "The posture is `BLOCKED` when any of the following holds: (a)
        any `AuditFinding` of the engagement is in `OPEN` status with `severity`
        `HIGH`".

        Design: Corner/errors/error_engagement_blocked_on_mark_ready
        """
        eng, _p = create_small_plan_engagement()
        filing = create_filing(eng["id"])
        entry = get_success_data(api_client.create_schedule_entry(
            create_schedule_entry_payload(filing["id"], schedule_type="I"), TPA))
        get_success_data(api_client.verify_schedule_entry(entry["id"], AUDITOR))
        get_success_data(api_client.mark_schedules_complete(filing["id"], TPA))
        finding = create_manual_finding(
            eng["id"], category="LATE_REMITTANCE", severity="HIGH",
            description="chronic late remittance")
        assert finding["status"] == "OPEN"
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "BLOCKED"
        resp = api_client.mark_ready(filing["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_BLOCKED)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "SCHEDULES_COMPLETE"


class TestSubmitEngagementGate:

    def _ready_filing_in_testing(self):
        """Engagement walked only to TESTING with a READY_TO_FILE filing."""
        eng, _p = create_small_plan_engagement()
        get_success_data(api_client.activate_engagement(eng["id"], SPONSOR))
        get_success_data(api_client.begin_testing(eng["id"], TPA))
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        set_clock("2026-07-15T00:00:00Z")
        return eng, filing

    def test_submit_requires_report_issued(self):
        """PRD §3.9: "The engagement must be in `REPORT_ISSUED` status; otherwise
        the submit is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/filing_submit_requires_report_issued
        """
        eng, filing = self._ready_filing_in_testing()
        resp = api_client.submit_filing(filing["id"], {}, MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "READY_TO_FILE"
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["status"] == "TESTING"

    def test_submit_succeeds_from_report_issued(self):
        """PRD §3.9: "An `EngagementManager` submits a `READY_TO_FILE` filing."
        PRD §3.9: "On a successful submit the filing's `filed_date` is set to the
        logical clock date, and `is_late` is computed as true when the
        `filed_date` is strictly later than the `effective_due_date` — filing
        exactly on the due date is timely."

        Design: Difficulty/cross_entity_state_dependency/filing_submit_requires_report_issued
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        set_clock("2026-07-15T00:00:00Z")
        submitted = validate_success(api_client.submit_filing(filing["id"], {}, MANAGER))
        assert submitted["status"] == "FILED"
        assert submitted["filed_date"] == "2026-07-15"
        assert submitted["is_late"] is False
        assert submitted["penalty_cents"] == 0


class TestAmendmentGate:

    def test_amendment_on_draft_filing_rejected(self):
        """PRD §3.9: "an amendment attempted from any status other than `ACCEPTED`
        is rejected with `ERR_AMENDMENT_NOT_ALLOWED` (HTTP 409)."

        Design: Corner/endpoints/amendment_on_non_accepted_filing_rejected
        """
        eng = create_engagement()
        filing = create_filing(eng["id"])
        resp = api_client.amend_filing(
            filing["id"],
            {"expected_filing_version": filing["version"],
             "amendment_reason": "too early"},
            TPA)
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "DRAFT"

    def test_stale_filing_version_rejected_on_amend(self):
        """PRD §2.8: "When amending an accepted filing (§3.9), the request must
        carry `expected_filing_version`, holding the client's last-observed
        `version` of the `Form5500Filing`. An amendment legitimately supersedes
        the accepted snapshot, so a writer holding a stale filing version is
        rejected with `ERR_STALE_FILING_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stale_filing_version_rejected_on_amend
        """
        eng, _p = create_engagement_in_report_issued()
        filing = create_filing(eng["id"])
        stale_version = filing["version"]  # captured at DRAFT
        entry = get_success_data(api_client.create_schedule_entry(
            create_schedule_entry_payload(filing["id"], schedule_type="I"), TPA))
        get_success_data(api_client.verify_schedule_entry(entry["id"], AUDITOR))
        get_success_data(api_client.mark_schedules_complete(filing["id"], TPA))
        get_success_data(api_client.mark_ready(filing["id"], MANAGER))
        set_clock("2026-07-15T00:00:00Z")
        get_success_data(api_client.submit_filing(filing["id"], {}, MANAGER))
        accepted = get_success_data(api_client.record_disposition(
            filing["id"], {"outcome": "ACCEPTED"}, SYSTEM))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["version"] > stale_version
        resp = api_client.amend_filing(
            filing["id"],
            {"expected_filing_version": stale_version,
             "amendment_reason": "stale view"},
            TPA)
        validate_error(resp, ApiErrorId.ERR_STALE_FILING_VERSION, expected_status=412)
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "ACCEPTED"
