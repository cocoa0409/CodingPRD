"""Incident filing, reporting deadline, compliance-case adjudication, cascades,
and the home open-case counter lifecycle."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_admission_payload, setup_admitted_resident, setup_incident_with_case,
    create_applicant, add_bed, create_pending_admission, file_incident, set_clock,
    assert_same_instant,
    fresh_home, fresh_incident, fresh_case, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestMinorIncidentClosure:
    def test_close_minor_on_major_rejected(self, api):
        """PRD §3.6: "A `MINOR` incident closes directly — `REPORTED` → `CLOSED`
        through the provider's minor-close action — without any compliance case."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/incident_close_minor_requires_minor_severity
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-01T12:00:00Z")
        incident = file_incident(ctx["resident"]["id"], "2026-06-01T06:00:00Z",
                                 severity="MAJOR", incident_type="FALL",
                                 description="Fall with bruise")
        res = api.close_minor_incident(incident["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert fresh_incident(incident["id"])["status"] == "REPORTED"

    def test_minor_incident_closes_without_case(self, api):
        """PRD §3.6: "A `MINOR` incident closes directly — `REPORTED` → `CLOSED`
        through the provider's minor-close action — without any compliance case."

        Design: Corner/validations/minor_incident_close_succeeds_without_case
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-01T12:00:00Z")
        incident = file_incident(ctx["resident"]["id"], "2026-06-01T06:00:00Z",
                                 severity="MINOR", incident_type="FALL",
                                 description="Minor stumble, no injury")
        closed = validate_success(api.close_minor_incident(incident["id"], PROVIDER),
                                  200)
        assert closed["status"] == "CLOSED"

    def test_minor_incident_creates_no_compliance_case(self, api):
        """PRD §3.6: "A `MINOR` incident closes directly — `REPORTED` → `CLOSED`
        through the provider's minor-close action — without any compliance case."
        PRD §2.11: "`open_case_count` counts the home's compliance cases in `OPEN` or
        `SUBSTANTIATED` status and is recomputed on every compliance-case status
        change."

        Design: Corner/validations/minor_incident_close_succeeds_without_case
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-01T12:00:00Z")
        incident = file_incident(ctx["resident"]["id"], "2026-06-01T06:00:00Z",
                                 severity="MINOR", incident_type="FALL",
                                 description="Minor stumble, no injury")
        validate_success(api.close_minor_incident(incident["id"], PROVIDER), 200)
        data, meta = validate_paginated(api.list_compliance_cases(
            PROVIDER, params={"incident_id": incident["id"]}))
        assert meta["total_count"] == 0, "a MINOR incident must never open a case"
        assert data == []
        assert fresh_home(ctx["home"]["id"])["open_case_count"] == 0


class TestReportingDeadlineBoundary:
    def test_exactly_24h_delay_opens_case(self, api):
        """PRD §3.6: "The boundary is strict: a delay of exactly twenty-four hours
        and zero minutes is not late, while twenty-four hours and one minute is."
        PRD §3.6: "For a `MAJOR` or `CRITICAL` incident, the provider opens a case:
        the incident moves `REPORTED` → `UNDER_REVIEW` and a linked compliance case
        is created in `OPEN`."

        Design: Difficulty/boundary_precision_check/report_deadline_exactly_24h_passes_24h01m_fails
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-09T00:00:00Z")
        incident = file_incident(ctx["resident"]["id"], "2026-06-08T00:00:00Z",
                                 severity="MAJOR", incident_type="FALL",
                                 description="Boundary pass case")
        case = validate_success(api.open_incident_case(incident["id"], PROVIDER), 201)
        assert case["status"] == "OPEN", \
            "a filing delay of exactly 24h00m is not late; the case must open"
        assert fresh_incident(incident["id"])["status"] == "UNDER_REVIEW"

    def test_24h01m_delay_refused_with_late_report(self, api):
        """PRD §3.6: "The delay from `occurred_at` to `reported_at` is measured in
        whole minutes and expressed in hours; a `MAJOR` or `CRITICAL` incident filed
        more than twenty-four hours after the event is still accepted, but a late
        flag is set on it, and the later attempt to open a compliance case from it is
        refused with `ERR_LATE_REPORT`."

        Design: Difficulty/boundary_precision_check/report_deadline_exactly_24h_passes_24h01m_fails
        """
        ctx = setup_admitted_resident()
        set_clock("2026-06-09T00:00:00Z")
        incident = file_incident(ctx["resident"]["id"], "2026-06-07T22:59:00Z",
                                 severity="MAJOR", incident_type="INJURY",
                                 description="Boundary fail case")
        res = api.open_incident_case(incident["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_LATE_REPORT, expected_status=422)
        assert fresh_incident(incident["id"])["status"] == "REPORTED", \
            "a refused open-case must leave the incident REPORTED"


class TestIncidentReopenCycle:
    def test_reopen_then_second_open_case_returns_under_review(self, api):
        """PRD §3.6: "If additional findings arrive, the review resets —
        `UNDER_REVIEW` → `REPORTED` — but only while the linked case is still `OPEN`;
        a case already substantiated or unfounded cannot be reopened through the
        incident, and the case itself stays `OPEN` through the reopen."
        PRD §3.6: "For a `MAJOR` or `CRITICAL` incident, the provider opens a case:
        the incident moves `REPORTED` → `UNDER_REVIEW` and a linked compliance case
        is created in `OPEN`."

        Design: Difficulty/non_linear_state_machine/incident_reopen_cycle_under_review_to_reported
        """
        ctx = setup_incident_with_case(filed_clock="2026-06-02T20:00:00Z",
                                       occurred_at="2026-06-02T10:00:00Z",
                                       description="Fall in hallway")
        incident, case = ctx["incident"], ctx["case"]
        validate_success(api.reopen_incident(incident["id"], PROVIDER), 200)
        assert fresh_incident(incident["id"])["status"] == "REPORTED"
        validate_success(api.open_incident_case(incident["id"], PROVIDER), 201)
        assert fresh_incident(incident["id"])["status"] == "UNDER_REVIEW", \
            "the cycle REPORTED -> UNDER_REVIEW must be traversable a second time"

    def test_case_stays_open_across_reopen_cycle(self, api):
        """PRD §3.6: "If additional findings arrive, the review resets —
        `UNDER_REVIEW` → `REPORTED` — but only while the linked case is still `OPEN`;
        a case already substantiated or unfounded cannot be reopened through the
        incident, and the case itself stays `OPEN` through the reopen."
        PRD §2.11: "`open_case_count` counts the home's compliance cases in `OPEN` or
        `SUBSTANTIATED` status and is recomputed on every compliance-case status
        change."

        Design: Difficulty/non_linear_state_machine/incident_reopen_cycle_under_review_to_reported
        """
        ctx = setup_incident_with_case(filed_clock="2026-06-02T20:00:00Z",
                                       occurred_at="2026-06-02T10:00:00Z",
                                       description="Fall in hallway")
        incident, case, home = ctx["incident"], ctx["case"], ctx["home"]
        validate_success(api.reopen_incident(incident["id"], PROVIDER), 200)
        validate_success(api.open_incident_case(incident["id"], PROVIDER), 201)
        assert fresh_case(case["id"])["status"] == "OPEN", \
            "the case must survive the reopen loop"
        assert fresh_home(home["id"])["open_case_count"] == 1


class TestSubstantiationCascade:
    def _setup_with_second_applicant(self, api):
        ctx = setup_incident_with_case(
            severity="CRITICAL", incident_type="ABUSE_ALLEGATION",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Allegation received")
        home = ctx["home"]
        bed2 = add_bed(home["id"], label="1B")
        waiting = create_applicant(home["id"], full_name="Res Wait",
                                   nursing_hours_per_week=1,
                                   adl_dependency_score=1)
        return ctx, bed2, waiting

    def test_abuse_citation_suspends_home(self, api):
        """PRD §3.6: "When the citation begins with WAC388-76-10 — the abuse and
        neglect findings — the home itself is suspended in the same step (`LICENSED`
        → `SUSPENDED`), blocking new admission approvals until reinstatement."
        PRD §3.6: "Substantiation requires the provider to supply a `citation_code`:
        the case moves `OPEN` → `SUBSTANTIATED`, `correction_plan_due_at` is set to
        the decision timestamp plus fourteen days, the linked incident bubbles up
        `UNDER_REVIEW` → `RESOLVED`, and the home's `open_case_count` is recomputed."

        Design: Difficulty/transitive_cascade/substantiate_abuse_citation_suspends_home
        """
        ctx, bed2, waiting = self._setup_with_second_applicant(api)
        substantiated = validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-76-10001"}, PROVIDER), 200)
        assert substantiated["status"] == "SUBSTANTIATED"
        assert fresh_incident(ctx["incident"]["id"])["status"] == "RESOLVED", \
            "the case decision must bubble the incident up to RESOLVED"
        home_after = fresh_home(ctx["home"]["id"])
        assert home_after["status"] == "SUSPENDED", \
            "an abuse citation must suspend the home in the same step"
        assert home_after["open_case_count"] == 1

    def test_suspended_home_blocks_new_admission_creation(self, api):
        """PRD §3.3: "Creation further requires the bed to be `AVAILABLE` and the
        bed's home to be `PROVISIONAL` or `LICENSED`."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/substantiate_abuse_citation_suspends_home
        """
        ctx, bed2, waiting = self._setup_with_second_applicant(api)
        validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-76-10001"}, PROVIDER), 200)
        bed2_now = validate_success(api.get_bed(bed2["id"], PROVIDER), 200)
        res = api.create_admission(
            create_admission_payload(waiting["resident"]["id"], bed2["id"],
                                     waiting["assessment"]["id"],
                                     bed2_now["version"],
                                     expected_admission_date="2026-06-10"),
            PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestReinstatement:
    def test_reinstate_blocked_while_open_cases(self, api):
        """PRD §3.1: "Reinstatement moves `SUSPENDED` → `LICENSED` and is permitted
        only when the home's `open_case_count` is zero — no compliance case in `OPEN`
        or `SUBSTANTIATED`."
        PRD §2.9: "State-machine legality — the target resource is in a from-state
        that permits the transition and is not terminally locked; failure yields
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reinstate_blocked_while_open_cases
        """
        ctx = setup_incident_with_case(
            severity="CRITICAL", incident_type="ABUSE_ALLEGATION",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Allegation")
        validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-76-10001"}, PROVIDER), 200)
        home_after = fresh_home(ctx["home"]["id"])
        assert home_after["status"] == "SUSPENDED"
        assert home_after["open_case_count"] == 1, \
            "a SUBSTANTIATED case still counts as open"
        res = api.reinstate_home(ctx["home"]["id"], PROVIDER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestCorrectionPlanDeadline:
    def test_correction_plan_due_fourteen_days_after_decision(self, api):
        """PRD §3.6: "Substantiation requires the provider to supply a
        `citation_code`: the case moves `OPEN` → `SUBSTANTIATED`,
        `correction_plan_due_at` is set to the decision timestamp plus fourteen days,
        the linked incident bubbles up `UNDER_REVIEW` → `RESOLVED`, and the home's
        `open_case_count` is recomputed."

        Design: Corner/cross_cutting_layers/correction_plan_due_at_set_fourteen_days_after_substantiation
        """
        ctx = setup_incident_with_case(
            severity="MAJOR", incident_type="INJURY",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Bruise from transfer")
        set_clock("2026-06-02T00:00:00Z")
        validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-75-1234"}, PROVIDER), 200)
        case_after = fresh_case(ctx["case"]["id"])
        assert case_after["status"] == "SUBSTANTIATED"
        assert_same_instant(case_after["correction_plan_due_at"],
                            "2026-06-16T00:00:00Z")
        assert fresh_home(ctx["home"]["id"])["status"] == "LICENSED", \
            "a citation without the WAC388-76-10 prefix must not suspend the home"

    def test_late_correction_plan_rejected(self, api):
        """PRD §3.6: "From `SUBSTANTIATED`, the provider submits
        `correction_plan_submitted_at`, which must be present and must not fall after
        `correction_plan_due_at`; a late or missing plan is rejected with
        `ERR_LATE_CORRECTION_PLAN`."

        Design: Corner/errors/err_late_correction_plan_triggered
        """
        ctx = setup_incident_with_case(
            severity="MAJOR", incident_type="MED_ERROR",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Wrong dose administered")
        set_clock("2026-06-02T00:00:00Z")
        validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-75-1234"}, PROVIDER), 200)
        case_after = fresh_case(ctx["case"]["id"])
        assert_same_instant(case_after["correction_plan_due_at"], "2026-06-16T00:00:00Z")
        res = api.close_case(ctx["case"]["id"],
                             {"correction_plan_submitted_at": "2026-06-17T00:00:00Z"},
                             PROVIDER)
        validate_error(res, ApiErrorId.ERR_LATE_CORRECTION_PLAN, expected_status=422)
        assert fresh_case(ctx["case"]["id"])["status"] == "SUBSTANTIATED", \
            "a rejected closure must leave the case SUBSTANTIATED"


class TestOpenCaseCountLifecycle:
    def test_open_case_count_tracks_case_lifecycle(self, api):
        """PRD §2.11: "`open_case_count` counts the home's compliance cases in `OPEN`
        or `SUBSTANTIATED` status and is recomputed on every compliance-case status
        change."

        Design: Corner/cross_cutting_layers/home_open_case_count_lifecycle
        """
        ctx = setup_incident_with_case(
            severity="MAJOR", incident_type="MED_ERROR",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Wrong dose")
        home_id = ctx["home"]["id"]
        assert fresh_home(home_id)["open_case_count"] == 1, "OPEN case counted"
        set_clock("2026-06-02T00:00:00Z")
        validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-75-1234"}, PROVIDER), 200)
        assert fresh_home(home_id)["open_case_count"] == 1, \
            "SUBSTANTIATED still counts as open"
        closed = validate_success(api.close_case(
            ctx["case"]["id"],
            {"correction_plan_submitted_at": "2026-06-10T00:00:00Z"}, PROVIDER), 200)
        assert closed["status"] == "CLOSED"
        assert fresh_home(home_id)["open_case_count"] == 0, \
            "closure must recompute the counter back to zero"

    def test_case_decision_bubbles_incident_to_resolved(self, api):
        """PRD §3.6: "Substantiation requires the provider to supply a
        `citation_code`: the case moves `OPEN` → `SUBSTANTIATED`,
        `correction_plan_due_at` is set to the decision timestamp plus fourteen days,
        the linked incident bubbles up `UNDER_REVIEW` → `RESOLVED`, and the home's
        `open_case_count` is recomputed."

        Design: Corner/cross_cutting_layers/home_open_case_count_lifecycle
        """
        ctx = setup_incident_with_case(
            severity="MAJOR", incident_type="MED_ERROR",
            occurred_at="2026-06-01T06:00:00Z", filed_clock="2026-06-01T12:00:00Z",
            description="Wrong dose")
        set_clock("2026-06-02T00:00:00Z")
        validate_success(api.substantiate_case(
            ctx["case"]["id"], {"citation_code": "WAC388-75-1234"}, PROVIDER), 200)
        assert fresh_incident(ctx["incident"]["id"])["status"] == "RESOLVED"
