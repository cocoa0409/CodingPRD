"""Difficulty queue A tests: transitive cascades (dispute correction, landlord suspension)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_same_instant,
    consent_application,
    create_applicant,
    create_application,
    create_and_resolve_income_verification,
    create_jurisdiction_rule,
    deliver_report,
    file_dispute_payload,
    get_application,
    get_landlord,
    get_record,
    get_report,
    list_notices,
    list_records,
    make_applicant_headers,
    make_landlord_headers,
    resolve_dispute_payload,
    run_record_searches,
    score_application,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    verify_identity,
)

SCREENER = TEST_USERS["screener_headers"]
SCR1 = TEST_USERS["screener_1_headers"]
SCR2 = TEST_USERS["screener_2_headers"]


class TestDisputeCorrectionCascadeReopensDecision:
    def _setup(self):
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
            records=[{"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                      "record_date": "2024-03-01T00:00:00Z", "description": "eviction filing"}],
            screener_headers=SCR1,
        )
        recs = list_records(report["id"])
        create_and_resolve_income_verification(app, 600000)
        score_application(app)
        report = deliver_report(report)
        api_client.decide_application(app["id"], "DENY", make_landlord_headers(landlord["id"]))
        notices = list_notices(app["id"])
        notice = notices[0]
        api_client.issue_notice(notice["id"], make_landlord_headers(landlord["id"]))
        resp = api_client.file_dispute(
            report["id"], file_dispute_payload([recs[0]["id"]], "eviction was vacated"),
            make_applicant_headers(applicant["id"]),
        )
        dispute = resp.json()["data"]
        api_client.start_reinvestigation(dispute["id"], SCR2)
        return landlord, applicant, app, report, recs, notice, dispute

    def test_correction_flips_recommendation_and_sets_reconsideration(self):
        """PRD §3.9: "Third, when that re-run flips the recommendation away
        from `RECOMMEND_DENY` to `RECOMMEND_APPROVE` or `RECOMMEND_CONDITIONAL`,
        the application's `requires_reconsideration` flag is set to true."

        Design: Difficulty/transitive_cascade/dispute_correction_cascade_reopens_decision
        """
        landlord, applicant, app, report, recs, notice, dispute = self._setup()
        api_client.resolve_dispute(
            dispute["id"], resolve_dispute_payload("CORRECTED", "record removed from bureau file"), SCR2
        )
        assert get_record(recs[0]["id"])["status"] == "REMOVED"
        report_after = get_report(report["id"])
        assert report_after["status"] == "AMENDED"
        assert report_after["included_record_count"] == 0
        app_after = get_application(app["id"])
        assert app_after["eviction_included_count"] == 0
        assert app_after["recommendation"] == "RECOMMEND_APPROVE", "flipped from RECOMMEND_DENY"
        assert app_after["requires_reconsideration"] is True

    def test_correction_cascade_does_not_rescind_notice(self):
        """PRD §3.9: "The recorded `decision` is not changed by the cascade;
        the landlord's recourse is to rescind the issued notice per §3.8."

        Design: Difficulty/transitive_cascade/dispute_correction_cascade_reopens_decision
        """
        landlord, applicant, app, report, recs, notice, dispute = self._setup()
        api_client.resolve_dispute(
            dispute["id"], resolve_dispute_payload("CORRECTED", "record removed from bureau file"), SCR2
        )
        notice_after = list_notices(app["id"])[0]
        assert notice_after["status"] == "ISSUED", (
            "rescission is a separate landlord act, not part of the cascade"
        )


class TestLandlordSuspensionCascadeRefundsUndelivered:
    def _setup(self):
        landlord, _ = setup_landlord_with_criteria()
        # app1: stop at SCREENING (report DRAFT, fee charged).
        applicant1 = create_applicant(full_name="Ann One", email="a1@x.com", ssn_last4="1111")
        app1 = create_application(landlord, applicant1, unit_state_code="TX",
                                  monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app1, applicant1)
        verify_identity(app1)
        app1 = submit_application(app1, landlord)
        report1 = run_record_searches(app1, credit_score=700)
        # app2: fully scored and delivered (fee charged, report DELIVERED).
        applicant2 = create_applicant(full_name="Bob Two", email="b2@x.com", ssn_last4="2222")
        app2 = create_application(landlord, applicant2, unit_state_code="TX",
                                  monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app2, applicant2)
        verify_identity(app2)
        app2 = submit_application(app2, landlord)
        report2 = run_record_searches(app2, credit_score=700)
        create_and_resolve_income_verification(app2, 600000)
        score_application(app2)
        report2 = deliver_report(report2)
        return landlord, app1, report1, app2, report2

    def test_suspend_cancels_applications_and_voids_undelivered_reports(self):
        """PRD §3.7: "The suspension then cascades: every application belonging
        to that landlord that is still in `DRAFT`, `SUBMITTED`, `SCREENING`, or
        `SCORED` moves to `CANCELLED`, and each cancelled application receives
        the same cleanup as a withdrawal — its `DRAFT` report is `VOIDED`, and
        its `fee_charged_cents` is refunded into `fee_balance_cents` whenever
        its report was never delivered."

        Design: Difficulty/transitive_cascade/landlord_suspension_cascade_refunds_undelivered
        """
        landlord, app1, report1, app2, report2 = self._setup()
        api_client.suspend_landlord(landlord["id"], TEST_USERS["admin_headers"])
        assert get_application(app1["id"])["status"] == "CANCELLED"
        assert get_report(report1["id"])["status"] == "VOIDED", "undelivered report voided"
        assert get_application(app2["id"])["status"] == "CANCELLED"
        assert get_report(report2["id"])["status"] == "DELIVERED", "delivered report survives the cascade"

    def test_suspend_refunds_only_undelivered_fees_and_stamps(self):
        """PRD §3.7: "The landlord's `status` becomes `SUSPENDED` and `suspended_at` is stamped with the clock."
        PRD §3.7: "As always, `fee_charged_cents` itself is a historical record and is never decremented by refunds."

        Design: Difficulty/transitive_cascade/landlord_suspension_cascade_refunds_undelivered
        """
        landlord, app1, report1, app2, report2 = self._setup()
        api_client.suspend_landlord(landlord["id"], TEST_USERS["admin_headers"])
        ll = get_landlord(landlord["id"])
        assert ll["fee_balance_cents"] == 3439, "3439 + 3439 charged, exactly one 3439 refund"
        assert ll["status"] == "SUSPENDED"
        assert_same_instant(ll["suspended_at"], "2026-08-01T00:00:00Z", "suspended_at")
