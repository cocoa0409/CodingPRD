"""Difficulty queue A tests: parallel identity/workflow dimensions and the report dispute cycle."""
from test_helpers import (
    TEST_USERS,
    api_client,
    consent_application,
    create_applicant,
    create_application,
    create_and_resolve_income_verification,
    create_jurisdiction_rule,
    deliver_report,
    file_dispute_payload,
    get_application,
    get_dispute,
    get_record,
    get_report,
    list_records,
    make_applicant_headers,
    make_landlord_headers,
    make_screener_headers,
    record_searches_payload,
    resolve_dispute_payload,
    run_record_searches,
    score_application,
    setup_landlord_with_criteria,
    submit_application,
    verify_identity,
)

SCREENER = TEST_USERS["screener_headers"]
SCR1 = TEST_USERS["screener_1_headers"]
SCR2 = TEST_USERS["screener_2_headers"]


class TestReportDisputeRedeliveryCycle:
    def _setup_to_redelivered(self):
        create_jurisdiction_rule(
            state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
            portable_report_acceptance_required=True,
        )
        landlord, _ = setup_landlord_with_criteria()
        applicant = create_applicant(residence_state="CA")
        app = create_application(landlord, applicant, unit_state_code="CA",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        report = run_record_searches(
            app, credit_score=700,
            records=[
                {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                 "record_date": "2024-03-01T00:00:00Z", "description": "eviction filing A"},
                {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                 "record_date": "2024-04-01T00:00:00Z", "description": "eviction filing B"},
            ],
            screener_headers=SCR1,
        )
        recs = list_records(report["id"])
        create_and_resolve_income_verification(app, 600000)
        score_application(app)
        report = deliver_report(report)
        resp = api_client.file_dispute(
            report["id"], file_dispute_payload([recs[0]["id"]], "record A is not mine"),
            make_applicant_headers(applicant["id"]),
        )
        dispute1 = resp.json()["data"]
        api_client.start_reinvestigation(dispute1["id"], SCR2)
        api_client.resolve_dispute(dispute1["id"], resolve_dispute_payload("CORRECTED", "record A removed"), SCR2)
        deliver_report(report)
        return landlord, applicant, app, report, recs, dispute1

    def test_second_dispute_reenters_under_dispute(self):
        """PRD §3.8: "Second and later disputes against a `RE_DELIVERED` report
        re-enter the same loop."

        Design: Difficulty/non_linear_state_machine/report_dispute_redelivery_cycle
        """
        landlord, applicant, app, report, recs, dispute1 = self._setup_to_redelivered()
        resp = api_client.file_dispute(
            report["id"], file_dispute_payload([recs[1]["id"]], "record B is also wrong"),
            make_applicant_headers(applicant["id"]),
        )
        dispute2 = resp.json()["data"]
        assert get_report(report["id"])["status"] == "UNDER_DISPUTE", (
            "second loop iteration after RE_DELIVERED"
        )
        assert get_record(recs[0]["id"])["status"] == "REMOVED"
        assert get_record(recs[1]["id"])["status"] == "DISPUTED"
        assert dispute2["status"] == "FILED"

    def test_correction_cascade_recomputes_included_count(self):
        """PRD §3.8: "A successful filing creates the **Dispute** in `FILED`,
        stamping `filed_at` with the clock and computing
        `reinvestigation_deadline` as thirty days from filing. The filing also
        cascades: the report moves from `DELIVERED` or `RE_DELIVERED` to
        `UNDER_DISPUTE`, every disputed record moves from `INCLUDED` to
        `DISPUTED`, and the report's `included_record_count` is recomputed."

        Design: Difficulty/non_linear_state_machine/report_dispute_redelivery_cycle
        """
        landlord, applicant, app, report, recs, dispute1 = self._setup_to_redelivered()
        api_client.file_dispute(
            report["id"], file_dispute_payload([recs[1]["id"]], "record B is also wrong"),
            make_applicant_headers(applicant["id"]),
        )
        assert get_report(report["id"])["included_record_count"] == 0
        assert get_dispute(dispute1["id"])["status"] == "RESOLVED_CORRECTED"


class TestApplicationParallelIdentityAndWorkflowDimensions:
    def test_identity_failure_does_not_touch_workflow_status(self):
        """PRD §3.2: "Identity verification runs on its own state dimension,
        independent of the application's main `status`, and is never advanced
        by it."

        Design: Difficulty/non_linear_state_machine/application_parallel_identity_and_workflow_dimensions
        """
        landlord, _ = setup_landlord_with_criteria()
        applicant = create_applicant(residence_state="TX")
        app = create_application(landlord, applicant, unit_state_code="TX",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        resp = api_client.verify_identity(
            app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 40}, SCREENER
        )
        data = resp.json()["data"]
        assert data["identity_status"] == "FAILED"
        assert data["status"] == "DRAFT", "workflow dimension untouched"

    def test_identity_retry_then_submit_leaves_identity_verified(self):
        """PRD §3.2: "an `evidence_score` of at least 70 — exactly 70 verifies,
        the boundary is inclusive — moves `identity_status` from `UNVERIFIED`
        or `FAILED` to `VERIFIED`, while anything below 70 moves it to (or
        keeps it in) `FAILED`, permitting a retry loop until attempts run out."

        Design: Difficulty/non_linear_state_machine/application_parallel_identity_and_workflow_dimensions
        """
        landlord, criteria = setup_landlord_with_criteria()
        applicant = create_applicant(residence_state="TX")
        app = create_application(landlord, applicant, unit_state_code="TX",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        api_client.verify_identity(app["id"], {"method": "KNOWLEDGE_BASED", "evidence_score": 40}, SCREENER)
        resp = api_client.verify_identity(
            app["id"], {"method": "DOCUMENT_REVIEW", "evidence_score": 85}, SCREENER
        )
        data = resp.json()["data"]
        assert data["identity_status"] == "VERIFIED"
        assert data["identity_attempts"] == 2
        resp = api_client.submit_application(app["id"], make_landlord_headers(landlord["id"]))
        submitted = resp.json()["data"]
        assert submitted["status"] == "SUBMITTED"
        assert submitted["identity_status"] == "VERIFIED", "identity dimension untouched by submit"
        assert submitted["criteria_id"] == criteria["id"]
