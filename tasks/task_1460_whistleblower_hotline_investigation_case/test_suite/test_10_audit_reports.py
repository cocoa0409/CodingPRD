"""Audit committee reporting: day-count dual variants, substantiation nested rounding,
window half-open membership, report lifecycle."""
from test_helpers import (
    ApiErrorId,
    activate_assignment,
    add_conducted_interview,
    add_determination,
    add_sealed_evidence,
    create_case,
    create_legal_hold_payload,
    create_remediation_action_payload,
    create_report_payload,
    create_review_payload,
    create_staff,
    get_case,
    make_acm_headers,
    make_admin_headers,
    make_officer_headers,
    make_reporter_headers,
    propose_assignment_auto,
    screen_clear,
    setup_case_closure_ready,
    setup_case_determination_review,
    setup_case_under_investigation,
    setup_standard_staff,
    submit_determination,
    triage_case,
    validate_error,
    validate_success,
    api_client,
)


class TestDaysToCloseDualVariant:
    """Difficulty: days_to_close_calendar_vs_hold_adjusted (2 tests).

    Scenario: one case received 2026-08-02, closure_ready 2026-09-11, one legal hold
    covering 2026-08-10..2026-08-19 (10 distinct UTC dates), released.
    """

    def _setup_closure_with_hold(self, api):
        staff = setup_standard_staff()
        api.set_clock("2026-08-02T00:00:00Z", make_admin_headers())
        case, _ = create_case(category="SAFETY",
                              description="Allegation of unsafe warehouse practice")
        triaged = triage_case(case["id"], staff["h_int"], confirmed_category="SAFETY",
                              subject_seniority="EXECUTIVE", financial_exposure_band="HIGH_1M")
        a1 = propose_assignment_auto(
            case["id"], triaged["version"], staff["h_int"])
        screen_clear(a1["id"], staff["h_int"])
        activate_assignment(a1["id"], staff["h_off"])
        case_now = get_case(case["id"], staff["h_off"])
        ctx = {"staff": staff, "case": case_now}
        add_conducted_interview(ctx)
        add_sealed_evidence(ctx)
        det = add_determination(ctx)
        submit_determination(ctx, det["id"])
        hold = validate_success(api.create_legal_hold(create_legal_hold_payload(
            case["id"], start_at="2026-08-10T00:00:00Z", end_at="2026-08-19T00:00:00Z",
        ), staff["h_off"]), expected_status=201)
        api.release_legal_hold(hold["id"], staff["h_off2"])
        api.set_clock("2026-09-11T00:00:00Z", make_admin_headers())
        api.review_determination(det["id"], create_review_payload(
            decision="APPROVE", review_notes="Reviewed and accepted.",
            notice_summary="Case closed with no findings disclosed.",
        ), staff["h_off2"])
        return staff

    def test_calendar_variant_reports_40_days(self, api):
        """PRD §3.9: "`avg_days_to_close_calendar` is the arithmetic mean, over the
        closure set, of each case's elapsed whole UTC days from `received_at` to
        `closure_ready_at` (partial days discarded)."

        Design: Difficulty/dual_variant_calc/days_to_close_calendar_vs_hold_adjusted
        """
        staff = self._setup_closure_with_hold(api)
        resp = api.create_audit_report(create_report_payload(
            period_start="2026-08-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        ), staff["h_off"])
        data = validate_success(resp, expected_status=201)
        assert data["total_closures"] == 1
        assert data["avg_days_to_close_calendar"] == 40.0, (
            f"2026-08-02 -> 2026-09-11 is 40 whole days, got {data['avg_days_to_close_calendar']}"
        )

    def test_hold_adjusted_variant_reports_30_days(self, api):
        """PRD §3.9: "`avg_days_to_close_hold_adjusted` uses the identical inputs
        but reduces each case's day count by the number of distinct UTC dates that
        lie within the case's received-to-closure-ready date range and are covered
        by at least one of the case's legal holds".

        Design: Difficulty/dual_variant_calc/days_to_close_calendar_vs_hold_adjusted
        """
        staff = self._setup_closure_with_hold(api)
        resp = api.create_audit_report(create_report_payload(
            period_start="2026-08-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
        ), staff["h_off"])
        data = validate_success(resp, expected_status=201)
        assert data["avg_days_to_close_hold_adjusted"] == 30.0, (
            "40 calendar days minus 10 hold-covered dates (2026-08-10..2026-08-19)"
        )
        assert data["avg_days_to_close_hold_adjusted"] != data["avg_days_to_close_calendar"]


class TestOrgSubstantiationNestedRounding:
    """Difficulty: org_substantiation_rate_nested_rounding_mode_b (2 tests).

    NORTH: N1 SUBSTANTIATED, N2 UNSUBSTANTIATED; SOUTH: S1 UNSUBSTANTIATED.
    All closure_ready on 2026-08-05; window [2026-08-01, 2026-09-01).
    """

    def _setup_three_closures(self, api):
        staff = setup_standard_staff()
        # N1: NORTH SUBSTANTIATED (through REMEDIATION via one rejected action)
        n1, _ = create_case(description="Allegation of expense fraud in Q2", region="NORTH")
        n1_t = triage_case(n1["id"], staff["h_int"])
        a1 = propose_assignment_auto(n1["id"], n1_t["version"], staff["h_int"])
        screen_clear(a1["id"], staff["h_int"])
        activate_assignment(a1["id"], staff["h_off"])
        ctx1 = {"staff": staff, "case": get_case(n1["id"], staff["h_off"])}
        add_conducted_interview(ctx1)
        add_sealed_evidence(ctx1)
        d1 = add_determination(ctx1, finding="SUBSTANTIATED",
                               rationale="Evidence reviewed shows the policy violation is supported beyond reasonable doubt.")
        submit_determination(ctx1, d1["id"])

        # N2: NORTH UNSUBSTANTIATED
        n2, _ = create_case(channel="EMAIL", category="HARASSMENT",
                            description="Allegation of hostile workplace conduct", region="NORTH")
        n2_t = triage_case(n2["id"], staff["h_int"], confirmed_category="HARASSMENT")
        a2 = propose_assignment_auto(n2["id"], n2_t["version"], staff["h_int"])
        screen_clear(a2["id"], staff["h_int"])
        activate_assignment(a2["id"], staff["h_off"])
        ctx2 = {"staff": staff, "case": get_case(n2["id"], staff["h_off"])}
        add_conducted_interview(ctx2, start="2026-08-04T10:00:00Z", end="2026-08-04T11:00:00Z")
        add_sealed_evidence(ctx2)
        d2 = add_determination(ctx2)
        submit_determination(ctx2, d2["id"])

        # S1: SOUTH UNSUBSTANTIATED
        s1, _ = create_case(channel="PHONE", category="DATA_PRIVACY",
                            description="Allegation of customer data mishandling", region="SOUTH")
        s1_t = triage_case(s1["id"], staff["h_int"], confirmed_category="DATA_PRIVACY")
        a3 = propose_assignment_auto(s1["id"], s1_t["version"], staff["h_int"])
        screen_clear(a3["id"], staff["h_int"])
        activate_assignment(a3["id"], staff["h_off"])
        ctx3 = {"staff": staff, "case": get_case(s1["id"], staff["h_off"])}
        add_conducted_interview(ctx3, start="2026-08-05T10:00:00Z", end="2026-08-05T11:00:00Z")
        add_sealed_evidence(ctx3)
        d3 = add_determination(ctx3)
        submit_determination(ctx3, d3["id"])

        api.set_clock("2026-08-05T00:00:00Z", make_admin_headers())
        # N1 approve (SUBSTANTIATED) -> REMEDIATION, then propose + REJECT action -> CLOSURE_READY
        api.review_determination(d1["id"], create_review_payload(
            decision="APPROVE", review_notes="Reviewed and accepted.",
            notice_summary="Case closed; corrective actions completed.",
        ), staff["h_off2"])
        ra = validate_success(api.create_remediation_action(
            d1["id"], create_remediation_action_payload(), staff["h_off"]), expected_status=201)
        api.decide_remediation_action(ra["id"], {"decision": "REJECT"}, staff["h_off2"])
        # N2, S1 approve (UNSUBSTANTIATED) -> CLOSURE_READY
        for d in (d2, d3):
            api.review_determination(d["id"], create_review_payload(
                decision="APPROVE", review_notes="Reviewed and accepted.",
                notice_summary="Case closed with no findings disclosed.",
            ), staff["h_off2"])
        return staff

    def test_org_rate_uses_nested_rounding(self, api):
        """PRD §3.9: "The rounding order is pinned — per-region rates are rounded
        first, then averaged, then the average is rounded". NORTH round(1/2,4)=0.5,
        SOUTH round(0/1,4)=0.0, mean=(0.5+0.0)/2=0.25.

        Design: Difficulty/combinatorial_formula/org_substantiation_rate_nested_rounding_mode_b
        """
        staff = self._setup_three_closures(api)
        resp = api.create_audit_report(create_report_payload(
            period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
        ), staff["h_off"])
        data = validate_success(resp, expected_status=201)
        assert data["total_closures"] == 3
        assert data["org_substantiation_rate"] == 0.25

    def test_pooled_rate_is_reference_variant(self, api):
        """PRD §3.9: "That alternative is exposed separately as
        `pooled_substantiation_rate`: the total count of `SUBSTANTIATED` closures in
        the window divided by the total closures in the window, rounded half-up to
        4 decimal places." (1/3 = 0.3333)

        Design: Difficulty/combinatorial_formula/org_substantiation_rate_nested_rounding_mode_b
        """
        staff = self._setup_three_closures(api)
        resp = api.create_audit_report(create_report_payload(
            period_start="2026-08-01T00:00:00Z", period_end="2026-09-01T00:00:00Z",
        ), staff["h_off"])
        data = validate_success(resp, expected_status=201)
        assert data["pooled_substantiation_rate"] == 0.3333
        assert data["org_substantiation_rate"] != data["pooled_substantiation_rate"]


class TestReportWindowMembership:
    def test_received_at_period_end_excluded(self, api):
        """PRD §3.9: "`total_received` counts cases whose `received_at` falls inside
        the window" and "a half-open window with the start inclusive and the end
        exclusive".

        Design: Corner/calculations/report_window_half_open_membership
        """
        s_off = create_staff(
            "Olivia Officer", "officer@corp.example", ["OFFICER"])
        create_case(description="Allegation of expense fraud case one")  # at 2026-08-01
        api.set_clock("2026-09-01T00:00:00Z", make_admin_headers())
        create_case(channel="PHONE", category="SAFETY",
                    description="Allegation of unsafe practice case two", region="SOUTH")
        resp = api.create_audit_report(create_report_payload(), make_officer_headers(s_off["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["total_received"] == 1, "case2 received exactly at period_end is excluded"


class TestReportLifecycle:
    def test_finalize_then_refinalize_rejected(self, api):
        """PRD §3.9: "finalizing a report that is not `DRAFT` fails with
        `ERR_REPORT_NOT_DRAFT`".

        Design: Corner/state_machines/report_finalize_locks_and_present_flow
        """
        s_off = create_staff(
            "Olivia Officer", "officer@corp.example", ["OFFICER"])
        resp = api.create_audit_report(create_report_payload(), make_officer_headers(s_off["id"]))
        report = validate_success(resp, expected_status=201)
        resp2 = api.finalize_audit_report(report["id"], make_officer_headers(s_off["id"]))
        assert validate_success(resp2)["status"] == "FINALIZED"
        resp3 = api.finalize_audit_report(report["id"], make_officer_headers(s_off["id"]))
        validate_error(resp3, ApiErrorId.ERR_REPORT_NOT_DRAFT)

    def test_present_after_finalize(self, api):
        """PRD §3.9: "Presentation, by an `AuditCommitteeMember` or a
        `ComplianceOfficer`, moves a `FINALIZED` report to `PRESENTED`".

        Design: Corner/state_machines/report_finalize_locks_and_present_flow
        """
        s_off = create_staff(
            "Olivia Officer", "officer@corp.example", ["OFFICER"])
        report = validate_success(api.create_audit_report(
            create_report_payload(), make_officer_headers(s_off["id"])), expected_status=201)
        api.finalize_audit_report(report["id"], make_officer_headers(s_off["id"]))
        resp = api.present_audit_report(report["id"], make_acm_headers())
        assert validate_success(resp)["status"] == "PRESENTED"

    def test_present_draft_rejected(self, api):
        """PRD §3.9: "moves a `FINALIZED` report to `PRESENTED` (otherwise
        `ERR_REPORT_NOT_FINALIZED`)".

        Design: Corner/errors/present_draft_report_rejected
        """
        s_off = create_staff(
            "Olivia Officer", "officer@corp.example", ["OFFICER"])
        report = validate_success(api.create_audit_report(
            create_report_payload(), make_officer_headers(s_off["id"])), expected_status=201)
        resp = api.present_audit_report(report["id"], make_acm_headers())
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FINALIZED)
