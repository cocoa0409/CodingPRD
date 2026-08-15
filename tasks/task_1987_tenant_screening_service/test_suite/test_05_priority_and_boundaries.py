"""Difficulty queue A tests: validation-priority pairs, numeric boundaries, cross-entity gates,
resource temporal overlap, and compensating invariants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_same_instant,
    consent_application,
    create_applicant,
    create_application,
    create_and_resolve_income_verification,
    create_criteria_payload,
    create_jurisdiction_rule,
    create_jurisdiction_rule_payload,
    deliver_report,
    file_dispute_payload,
    get_application,
    get_criteria,
    get_record,
    get_report,
    list_records,
    make_applicant_headers,
    make_landlord_headers,
    record_searches_payload,
    resolve_dispute_payload,
    run_record_searches,
    score_application,
    set_clock,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
    verify_identity,
)

ADMIN = TEST_USERS["admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
SCR1 = TEST_USERS["screener_1_headers"]
SCR2 = TEST_USERS["screener_2_headers"]
SCR3 = TEST_USERS["screener_3_headers"]


class TestWithdrawnAppSearchStateBeatsConsent:
    def _setup_withdrawn_without_consent(self):
        landlord, _ = setup_landlord_with_criteria()
        applicant = create_applicant()
        app = create_application(landlord, applicant, unit_state_code="TX",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        api_client.withdraw_application(app["id"], make_landlord_headers(landlord["id"]))
        return app

    def test_terminal_state_error_wins_over_consent(self):
        """PRD §2.6: "6. **Resource from-state.** The target resource must be in the state the operation requires. Terminal applications fail with `ERR_APPLICATION_TERMINAL`;"
        PRD §2.6: "8. **Compliance gates**, evaluated in their own pinned relative order: applicant consent before any bureau search (`ERR_CONSENT_REQUIRED`),"

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_app_search_state_beats_consent
        """
        app = self._setup_withdrawn_without_consent()
        resp = api_client.record_searches(app["id"], record_searches_payload(700, []), SCREENER)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_TERMINAL)

    def test_withdrawn_search_leaves_application_withdrawn(self):
        """PRD §2.6: "Terminal applications fail with `ERR_APPLICATION_TERMINAL`; other wrong states fail with the resource's own state error"

        Design: Difficulty/priority_pair_validation_conflict/withdrawn_app_search_state_beats_consent
        """
        app = self._setup_withdrawn_without_consent()
        api_client.record_searches(app["id"], record_searches_payload(700, []), SCREENER)
        assert get_application(app["id"])["status"] == "WITHDRAWN"


class TestLateDisputeWithForeignRecordTemporalBeatsReferential:
    def _setup_two_delivered_reports(self):
        create_jurisdiction_rule(
            state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
            portable_report_acceptance_required=True,
        )
        landlord, _ = setup_landlord_with_criteria()

        applicant1 = create_applicant(full_name="Ann One", email="a1@x.com", ssn_last4="1111", residence_state="CA")
        app1 = create_application(landlord, applicant1, unit_state_code="CA",
                                  monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app1, applicant1)
        verify_identity(app1)
        app1 = submit_application(app1, landlord)
        report1 = run_record_searches(app1, credit_score=700, records=[
            {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
             "record_date": "2024-03-01T00:00:00Z", "description": "eviction A"},
        ])
        r1 = list_records(report1["id"])[0]
        create_and_resolve_income_verification(app1, 600000)
        score_application(app1)
        deliver_report(report1)

        applicant2 = create_applicant(full_name="Bob Two", email="b2@x.com", ssn_last4="2222", residence_state="CA")
        app2 = create_application(landlord, applicant2, unit_state_code="CA",
                                  monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app2, applicant2)
        verify_identity(app2)
        app2 = submit_application(app2, landlord)
        report2 = run_record_searches(app2, credit_score=700, records=[
            {"record_type": "CRIMINAL", "jurisdiction_state_code": "CA",
             "record_date": "2023-05-01T00:00:00Z", "description": "misdemeanor B"},
        ])
        r2 = list_records(report2["id"])[0]
        create_and_resolve_income_verification(app2, 600000)
        score_application(app2)
        deliver_report(report2)
        return landlord, applicant1, report1, r2

    def test_window_closed_wins_over_foreign_record(self):
        """PRD §2.6: "9. **Clock-relative windows.** Temporal gates fail with `ERR_DISPUTE_WINDOW_CLOSED`, `ERR_PORTABLE_REPORT_EXPIRED`, or `ERR_REINVESTIGATION_OVERDUE` (all HTTP 422), per the window rules in §3."
        PRD §2.6: "11. **Referential integrity of dispute payloads.** Every id in a dispute's `disputed_record_ids` must belong to the dispute's report, failing with `ERR_RECORD_NOT_ON_REPORT` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/late_dispute_with_foreign_record_temporal_beats_referential
        """
        landlord, applicant1, report1, r2 = self._setup_two_delivered_reports()
        set_clock("2026-09-15T00:00:00Z")
        resp = api_client.file_dispute(
            report1["id"],
            file_dispute_payload([r2["id"]], "late filing that also references a foreign record"),
            make_applicant_headers(applicant1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)

    def test_late_foreign_dispute_leaves_report_untouched(self):
        """PRD §3.8: "the filing clock must be no later than the report's
        `last_delivered_at` plus thirty days, inclusive — filing exactly on
        the deadline day is allowed, and a later filing is rejected with
        `ERR_DISPUTE_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/late_dispute_with_foreign_record_temporal_beats_referential
        """
        landlord, applicant1, report1, r2 = self._setup_two_delivered_reports()
        set_clock("2026-09-15T00:00:00Z")
        api_client.file_dispute(
            report1["id"],
            file_dispute_payload([r2["id"]], "late filing"),
            make_applicant_headers(applicant1["id"]),
        )
        assert get_report(report1["id"])["status"] == "DELIVERED"


class TestIncomeRatioExactThresholdPasses:
    def _setup_scored(self, verified_income):
        landlord, _ = setup_landlord_with_criteria()
        applicant = create_applicant(residence_state="TX")
        app = create_application(landlord, applicant, unit_state_code="TX",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        run_record_searches(app, credit_score=700)
        create_and_resolve_income_verification(app, verified_income)
        return score_application(app)

    def test_income_exactly_at_threshold_passes(self):
        """PRD §3.6: "the application passes when `verified_income_cents` is
        not null and is at least the threshold — income exactly equal to the
        threshold passes."

        Design: Difficulty/boundary_precision_check/income_ratio_exact_threshold_passes
        """
        scored = self._setup_scored(600000)
        assert scored["affordability_passes"] is True, "600000 >= 600000: inclusive boundary passes"
        assert scored["recommendation"] == "RECOMMEND_APPROVE"

    def test_income_one_cent_below_threshold_fails(self):
        """PRD §3.6: "In the **standard variant**, the pass threshold is the pinned criteria's `income_multiplier` times the application's `monthly_rent_cents`, rounded half-up to integer cents;"

        Design: Difficulty/boundary_precision_check/income_ratio_exact_threshold_passes
        """
        scored = self._setup_scored(599999)
        assert scored["affordability_passes"] is False, "599999 < 600000"
        assert scored["recommendation"] == "RECOMMEND_DENY"


class TestScoreBlockedUntilIncomeVerificationResolved:
    def _setup_screening_with_pending_iv(self):
        landlord, _ = setup_landlord_with_criteria()
        applicant = create_applicant()
        app = create_application(landlord, applicant, unit_state_code="TX",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        run_record_searches(app, credit_score=700)
        resp = api_client.create_income_verification(app["id"], {"employer_name": "Acme"}, SCREENER)
        iv = resp.json()["data"]
        return app, iv

    def test_pending_income_verification_blocks_score(self):
        """PRD §3.6: "It is gated on income: the application's income
        verification must exist and be resolved to `VERIFIED` or `FAILED` — a
        missing or still-`PENDING` verification rejects the score with
        `ERR_INCOME_VERIFICATION_UNRESOLVED`."

        Design: Difficulty/cross_entity_state_dependency/score_blocked_until_income_verification_resolved
        """
        app, iv = self._setup_screening_with_pending_iv()
        resp = api_client.score_application(app["id"], SCREENER)
        validate_error(resp, ApiErrorId.ERR_INCOME_VERIFICATION_UNRESOLVED)

    def test_resolved_income_verification_unblocks_score(self):
        """PRD §3.6: "Scoring is a `Screener` operation that moves a `SCREENING` application to `SCORED`"

        Design: Difficulty/cross_entity_state_dependency/score_blocked_until_income_verification_resolved
        """
        app, iv = self._setup_screening_with_pending_iv()
        api_client.resolve_income_verification(
            iv["id"], {"outcome": "VERIFIED", "verified_monthly_income_cents": 600000}, SCREENER
        )
        scored = score_application(app)
        assert scored["status"] == "SCORED"
        assert scored["recommendation"] == "RECOMMEND_APPROVE"


class TestDisputeRequiresReportDelivered:
    def _setup_draft_report(self):
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
        report = run_record_searches(app, credit_score=700, records=[
            {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
             "record_date": "2024-03-01T00:00:00Z", "description": "eviction filing"},
        ])
        recs = list_records(report["id"])
        return landlord, applicant, app, report, recs

    def test_dispute_on_draft_report_rejected(self):
        """PRD §3.8: "The owning `Applicant` files a dispute against a report, which must be `DELIVERED` or `RE_DELIVERED` (any other report state yields `ERR_INVALID_REPORT_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_report_delivered
        """
        landlord, applicant, app, report, recs = self._setup_draft_report()
        resp = api_client.file_dispute(
            report["id"], file_dispute_payload([recs[0]["id"]], "filed too early"),
            make_applicant_headers(applicant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REPORT_STATE)

    def test_dispute_after_delivery_moves_report_and_records(self):
        """PRD §3.8: "The filing also cascades: the report moves from
        `DELIVERED` or `RE_DELIVERED` to `UNDER_DISPUTE`, every disputed record
        moves from `INCLUDED` to `DISPUTED`, and the report's
        `included_record_count` is recomputed."

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_report_delivered
        """
        landlord, applicant, app, report, recs = self._setup_draft_report()
        create_and_resolve_income_verification(app, 600000)
        score_application(app)
        deliver_report(report)
        resp = api_client.file_dispute(
            report["id"], file_dispute_payload([recs[0]["id"]], "now filed after delivery"),
            make_applicant_headers(applicant["id"]),
        )
        dispute = validate_success(resp, expected_status=201)
        assert dispute["status"] == "FILED"
        assert get_report(report["id"])["status"] == "UNDER_DISPUTE"
        assert get_record(recs[0]["id"])["status"] == "DISPUTED"
        assert get_report(report["id"])["included_record_count"] == 0


class TestJurisdictionRuleHalfOpenWindowOverlap:
    def test_adjacent_half_open_windows_are_accepted(self):
        """PRD §3.1: "Two rules for the same `state_code` may touch — one rule's `effective_to` equal to the other's `effective_from` is legal adjacency — but their windows may never overlap;"

        Design: Difficulty/resource_temporal_overlap/jurisdiction_rule_half_open_window_overlap
        """
        set_clock()
        create_jurisdiction_rule(
            state_code="CA", effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z"
        )
        resp = api_client.create_jurisdiction_rule(
            create_jurisdiction_rule_payload(
                state_code="CA", criminal_lookback_years=5, eviction_lookback_years=5,
                source_of_income_protected=True, portable_report_acceptance_required=True,
                effective_from="2026-06-01T00:00:00Z",
            ),
            ADMIN,
        )
        rule2 = validate_success(resp, expected_status=201)
        assert_same_instant(rule2["effective_from"], "2026-06-01T00:00:00Z", "effective_from")

    def test_overlapping_half_open_windows_rejected(self):
        """PRD §3.1: "a violating creation is rejected with
        `ERR_RULE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/jurisdiction_rule_half_open_window_overlap
        """
        set_clock()
        create_jurisdiction_rule(
            state_code="CA", effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-01T00:00:00Z"
        )
        resp = api_client.create_jurisdiction_rule(
            create_jurisdiction_rule_payload(
                state_code="CA", criminal_lookback_years=3, eviction_lookback_years=3,
                effective_from="2026-05-31T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_RULE_WINDOW_OVERLAP)


class TestCriteriaClosedWindowTouchingEndpointsConflict:
    def _setup(self):
        set_clock()
        landlord = None
        from test_helpers import create_landlord, get_landlord
        landlord = create_landlord(name="L Win", contact_email="lwin@x.com")
        c1 = api_client.create_criteria(
            create_criteria_payload(name="C1", effective_from="2026-01-01T00:00:00Z",
                                    effective_to="2026-06-30T00:00:00Z"),
            make_landlord_headers(landlord["id"]),
        ).json()["data"]
        api_client.publish_criteria(
            c1["id"], {"expected_landlord_version": landlord["version"]},
            make_landlord_headers(landlord["id"]),
        )
        landlord = get_landlord(landlord["id"])
        return landlord

    def test_touching_closed_windows_conflict(self):
        """PRD §3.1: "the set's closed effective window must not overlap the
        closed window of any other `PUBLISHED` set belonging to the same
        landlord, and because both endpoints of a closed window are inclusive,
        two sets whose windows merely touch at an endpoint are in conflict;
        violations are rejected with `ERR_CRITERIA_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/criteria_closed_window_touching_endpoints_conflict
        """
        landlord = self._setup()
        c2 = api_client.create_criteria(
            create_criteria_payload(name="C2", min_credit_score=700, income_multiplier=3.5,
                                    guarantor_policy="INDEPENDENT_ONLY", accepts_portable_reports=False,
                                    effective_from="2026-06-30T00:00:00Z",
                                    effective_to="2026-12-31T00:00:00Z"),
            make_landlord_headers(landlord["id"]),
        ).json()["data"]
        resp = api_client.publish_criteria(
            c2["id"], {"expected_landlord_version": landlord["version"]},
            make_landlord_headers(landlord["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CRITERIA_WINDOW_OVERLAP)
        assert get_criteria(c2["id"])["status"] == "DRAFT", "failed publish does not mutate"

    def test_disjoint_closed_window_publishes(self):
        """PRD §3.1: "A successful publish stamps `published_at` with the
        clock and increments the landlord's `version` by one."

        Design: Difficulty/resource_temporal_overlap/criteria_closed_window_touching_endpoints_conflict
        """
        landlord = self._setup()
        c3 = api_client.create_criteria(
            create_criteria_payload(name="C3", min_credit_score=700, income_multiplier=3.5,
                                    guarantor_policy="INDEPENDENT_ONLY", accepts_portable_reports=False,
                                    effective_from="2026-07-01T00:00:00Z",
                                    effective_to="2026-12-31T00:00:00Z"),
            make_landlord_headers(landlord["id"]),
        ).json()["data"]
        resp = api_client.publish_criteria(
            c3["id"], {"expected_landlord_version": landlord["version"]},
            make_landlord_headers(landlord["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "PUBLISHED", "disjoint closed window publishes cleanly"


class TestDisputeUpholdRestoresIncludedRecordCount:
    def _setup_under_reinvestigation(self):
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
        report = run_record_searches(app, credit_score=700, records=[
            {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
             "record_date": "2024-03-01T00:00:00Z", "description": "eviction A"},
            {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
             "record_date": "2024-04-01T00:00:00Z", "description": "eviction B"},
        ], screener_headers=SCR1)
        recs = list_records(report["id"])
        create_and_resolve_income_verification(app, 600000)
        score_application(app)
        report = deliver_report(report)
        resp = api_client.file_dispute(
            report["id"],
            file_dispute_payload([recs[0]["id"], recs[1]["id"]], "both records are inaccurate"),
            make_applicant_headers(applicant["id"]),
        )
        dispute = resp.json()["data"]
        api_client.start_reinvestigation(dispute["id"], SCR2)
        return report, recs, dispute

    def test_uphold_restores_pre_dispute_included_count(self):
        """PRD §3.9: "An `UPHELD` resolution moves the dispute to
        `RESOLVED_UPHELD` and restores the status quo: every disputed record
        returns from `DISPUTED` to `INCLUDED`, the report moves from
        `UNDER_DISPUTE` to `RE_DELIVERED`, `included_record_count` is restored
        to its pre-dispute value, and `last_delivered_at` is refreshed to the
        clock, opening a fresh thirty-day dispute window."

        Design: Difficulty/compensating_invariant/dispute_uphold_restores_included_record_count
        """
        report, recs, dispute = self._setup_under_reinvestigation()
        api_client.resolve_dispute(dispute["id"], resolve_dispute_payload("UPHELD", "records verified accurate"), SCR2)
        report_after = get_report(report["id"])
        assert report_after["included_record_count"] == 2, (
            "the forward + compensating pair leaves the conserved count unchanged"
        )
        assert get_record(recs[0]["id"])["status"] == "INCLUDED"
        assert get_record(recs[1]["id"])["status"] == "INCLUDED"

    def test_uphold_re_delivers_and_refreshes_last_delivered(self):
        """PRD §3.9: "the report moves from `UNDER_DISPUTE` to `RE_DELIVERED`,
        `included_record_count` is restored to its pre-dispute value, and
        `last_delivered_at` is refreshed to the clock, opening a fresh
        thirty-day dispute window."

        Design: Difficulty/compensating_invariant/dispute_uphold_restores_included_record_count
        """
        report, recs, dispute = self._setup_under_reinvestigation()
        api_client.resolve_dispute(dispute["id"], resolve_dispute_payload("UPHELD", "records verified accurate"), SCR2)
        report_after = get_report(report["id"])
        assert report_after["status"] == "RE_DELIVERED"
        assert_same_instant(report_after["last_delivered_at"], "2026-08-01T00:00:00Z",
                            "last_delivered_at refreshed")


class TestWithdrawRefundRestoresFeeBalance:
    def _setup_screening(self):
        landlord, _ = setup_landlord_with_criteria()
        applicant = create_applicant()
        app = create_application(landlord, applicant, unit_state_code="TX",
                                 monthly_rent_cents=200000, stated_monthly_income_cents=600000)
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        report = run_record_searches(app, credit_score=700)
        return landlord, app, report

    def test_withdraw_before_delivery_refunds_full_fee(self):
        """PRD §3.7: "Withdrawal moves the application to `WITHDRAWN` and
        cleans up in-flight work: a report still in `DRAFT` is `VOIDED`, and
        when `fee_charged_cents` is above zero and the application's report
        has never been delivered — `delivered_at` still null — the charged
        fee is refunded into the landlord's `fee_balance_cents`, so the charge
        and the refund net to zero."

        Design: Difficulty/compensating_invariant/withdraw_refund_restores_fee_balance
        """
        landlord, app, report = self._setup_screening()
        from test_helpers import get_landlord
        assert get_landlord(landlord["id"])["fee_balance_cents"] == 3439
        api_client.withdraw_application(app["id"], make_landlord_headers(landlord["id"]))
        assert get_landlord(landlord["id"])["fee_balance_cents"] == 0, (
            "charge + compensating refund nets to zero"
        )
        assert get_report(report["id"])["status"] == "VOIDED", "undelivered DRAFT report voided"

    def test_withdraw_keeps_historical_fee_charged(self):
        """PRD §3.7: "As always, `fee_charged_cents` itself is a historical
        record and is never decremented by refunds."

        Design: Difficulty/compensating_invariant/withdraw_refund_restores_fee_balance
        """
        landlord, app, report = self._setup_screening()
        api_client.withdraw_application(app["id"], make_landlord_headers(landlord["id"]))
        app_after = get_application(app["id"])
        assert app_after["status"] == "WITHDRAWN"
        assert app_after["fee_charged_cents"] == 3439, "historical charge retained"
