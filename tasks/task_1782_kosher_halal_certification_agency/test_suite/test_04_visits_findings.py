"""Supervision visits, findings, remediation, and the nonconformance score."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    create_facility_for,
    create_prospect_client,
    get_client,
    make_client_contact_headers,
    make_supervisor_headers,
    raise_finding,
    schedule_visit,
    set_clock,
    setup_certified_client,
    start_routine_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVisitStateAndAssignment:
    def test_visit_complete_before_start_rejected(self, api):
        """PRD section 3.5: "Completion moves `IN_PROGRESS` → `COMPLETED` under
        the same assignment check." PRD section 3.5: "a wrong state yields
        `ERR_VISIT_INVALID_STATE`".

        Design: Corner/state_machines/visit_complete_before_start_rejected
        """
        client = create_prospect_client(legal_name="SM4 Co")
        facility = create_facility_for(client["id"], name="F4")
        visit = schedule_visit(facility["id"], visit_type="ROUTINE",
                               inspector_user_id="sup-1")
        assert visit["status"] == "SCHEDULED"
        resp = api.complete_visit(visit["id"], make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_VISIT_INVALID_STATE)

    def test_supervisor_cannot_start_unassigned_visit(self, api):
        """PRD section 2.1: "a `FieldSupervisor` may start, complete, declare
        no-access on, or raise findings only on visits whose `inspector_user_id`
        equals `X-User-ID`, and may complete a holiday window only when its
        `assigned_supervisor_id` equals `X-User-ID`; violations are rejected
        with `ERR_NOT_ASSIGNED_INSPECTOR` (HTTP 403)."

        Design: Corner/validations/supervisor_cannot_start_unassigned_visit
        """
        client = create_prospect_client(legal_name="RB2 Co")
        facility = create_facility_for(client["id"], name="FR2")
        visit = schedule_visit(facility["id"], visit_type="ROUTINE",
                               inspector_user_id="sup-1",
                               scheduled_start="2026-08-02T09:00:00Z",
                               scheduled_end="2026-08-02T12:00:00Z")
        set_clock("2026-08-02T10:00:00Z")
        resp = api.start_visit(visit["id"], make_supervisor_headers("sup-2"))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR)


class TestUnannouncedVisitVisibility:
    def test_unannounced_visit_hidden_from_client_contact(
            self, api, account_manager_headers):
        """PRD section 2.5: "an `UNANNOUNCED` visit is treated as non-existent
        for any `ClientContact` caller — it is absent from their list responses
        and returns 404 on direct fetch — so that unannounced inspections remain
        genuinely unannounced."

        Design: Corner/validations/unannounced_visit_hidden_from_client_contact
        """
        client = create_prospect_client(legal_name="UN Co")
        facility = create_facility_for(client["id"], name="FUN")
        visit = schedule_visit(
            facility["id"], visit_type="UNANNOUNCED",
            inspector_user_id="sup-5",
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T12:00:00Z", as_reviewer=True)

        cc = make_client_contact_headers(client["id"])
        resp = api.get_visit(visit["id"], cc)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        rows, meta = validate_paginated(api.list_visits(cc))
        assert meta["total_count"] == 0 and rows == [], (
            "UNANNOUNCED rows must be filtered out of ClientContact lists")

        agency_read = validate_success(api.get_visit(visit["id"],
                                                     account_manager_headers))
        assert agency_read["status"] == "SCHEDULED"

    def test_account_manager_cannot_create_unannounced_visit(
            self, api, account_manager_headers):
        """PRD section 3.5: "`UNANNOUNCED` visits may be created only by a
        `CertificationReviewer` — any other role, including `AccountManager`, is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/validations/account_manager_cannot_create_unannounced_visit
        """
        client = create_prospect_client(legal_name="AM Co")
        facility = create_facility_for(client["id"], name="FAM")
        resp = api.create_visit(
            {"facility_id": facility["id"], "visit_type": "UNANNOUNCED",
             "inspector_user_id": "sup-5",
             "scheduled_start": "2026-08-05T09:00:00Z",
             "scheduled_end": "2026-08-05T12:00:00Z"},
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        routine = validate_success(
            api.create_visit(
                {"facility_id": facility["id"], "visit_type": "ROUTINE",
                 "inspector_user_id": "sup-5",
                 "scheduled_start": "2026-08-05T09:00:00Z",
                 "scheduled_end": "2026-08-05T12:00:00Z"},
                account_manager_headers), 201)
        assert routine["status"] == "SCHEDULED"


class TestNoAccessCascade:
    def test_no_access_visit_autocreates_critical_finding_and_suspends(
            self, api, reviewer_headers):
        """PRD section 3.5: "an `InspectionFinding` is auto-created with
        severity `CRITICAL`, `origin` `AUTO_NO_ACCESS` (manually raised findings
        carry origin `MANUAL`), `status` `OPEN`, and a `remediation_deadline`
        exactly 7 days after the declaration instant; the client's
        `open_nc_score` is recomputed, rising by the critical weight of 8; if
        the facility was `APPROVED` it is suspended, which suspends in-scope
        `ACTIVE` certificates, which recomputes the client; and every equipment
        line at the facility is compromised".

        Design: Corner/state_machines/no_access_visit_autocreates_critical_finding_and_suspends
        """
        ctx = setup_certified_client(legal_name="SM11 Co")
        visit = schedule_visit(ctx["facility"]["id"], visit_type="ROUTINE",
                               inspector_user_id="sup-1",
                               scheduled_start="2026-08-03T09:00:00Z",
                               scheduled_end="2026-08-03T12:00:00Z")
        set_clock("2026-08-03T10:00:00Z")
        gone = validate_success(api.no_access_visit(
            visit["id"], make_supervisor_headers("sup-1")))
        assert gone["status"] == "NO_ACCESS"

        findings, _meta = validate_paginated(
            api.list_visit_findings(visit["id"], reviewer_headers))
        assert len(findings) == 1, "exactly one auto finding must be created"
        auto = findings[0]
        assert auto["severity"] == "CRITICAL"
        assert auto["origin"] == "AUTO_NO_ACCESS"
        assert auto["status"] == "OPEN"
        assert_instant_equals(auto["remediation_deadline"],
                              "2026-08-10T10:00:00Z", "declaration + 7 days")

        facility = validate_success(api.get_facility(ctx["facility"]["id"],
                                                     reviewer_headers))
        assert facility["status"] == "SUSPENDED"
        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    reviewer_headers))
        assert cert["status"] == "SUSPENDED"
        client = get_client(ctx["client"]["id"])
        assert client["status"] == "SUSPENDED"
        assert client["open_nc_score"] == 8
        assert client["risk_tier"] == "HIGH"
        line = validate_success(api.get_equipment_line(ctx["line"]["id"],
                                                       reviewer_headers))
        assert line["kosherization_state"] == "COMPROMISED"


class TestRemediationAndVerification:
    def test_finding_remediation_on_verified_closed_rejected(self, api):
        """PRD section 3.6: "The client responds to a finding in `OPEN`,
        `REOPENED`, or `ESCALATED` by submitting remediation". PRD section 3.6:
        "Verifying with `outcome` `CLOSED` lands the finding in the terminal
        state `VERIFIED_CLOSED`".

        Design: Corner/state_machines/finding_remediation_on_verified_closed_rejected
        """
        client = create_prospect_client(legal_name="SM5 Co")
        facility = create_facility_for(client["id"], name="F5")
        visit = start_routine_visit(facility["id"], inspector_user_id="sup-1",
                                    start="2026-08-02T09:00:00Z",
                                    end="2026-08-02T12:00:00Z",
                                    clock_into_window="2026-08-02T10:00:00Z")
        finding = raise_finding(visit["id"], "sup-1", severity="MINOR",
                                remediation_deadline="2026-09-01T00:00:00Z")
        cc = make_client_contact_headers(client["id"])
        validate_success(api.submit_remediation(finding["id"], "fixed", cc))
        closed = validate_success(api.verify_finding(
            finding["id"], {"outcome": "CLOSED"}, make_supervisor_headers("sup-2")))
        assert closed["status"] == "VERIFIED_CLOSED"

        resp = api.submit_remediation(finding["id"], "again", cc)
        validate_error(resp, ApiErrorId.ERR_FINDING_INVALID_STATE)

    def test_verify_by_original_inspector_rejected_segregation(self, api):
        """PRD section 2.9: "a `FieldSupervisor` verifying a remediation must
        not be the same supervisor whose visit raised the finding; equality with
        the visit's `inspector_user_id` yields
        `ERR_SEGREGATION_OF_DUTIES_VERIFICATION` (HTTP 403)."

        Design: Corner/validations/verify_by_original_inspector_rejected_segregation
        """
        client = create_prospect_client(legal_name="RB3 Co")
        facility = create_facility_for(client["id"], name="FR3")
        visit = start_routine_visit(facility["id"], inspector_user_id="sup-1",
                                    start="2026-08-02T09:00:00Z",
                                    end="2026-08-02T12:00:00Z",
                                    clock_into_window="2026-08-02T10:00:00Z")
        finding = raise_finding(visit["id"], "sup-1", severity="MINOR",
                                remediation_deadline="2026-09-01T00:00:00Z")
        cc = make_client_contact_headers(client["id"])
        validate_success(api.submit_remediation(finding["id"], "done", cc))

        resp = api.verify_finding(finding["id"], {"outcome": "CLOSED"},
                                  make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VERIFICATION)

        verified = validate_success(api.verify_finding(
            finding["id"], {"outcome": "CLOSED"}, make_supervisor_headers("sup-2")))
        assert verified["status"] == "VERIFIED_CLOSED"


class TestNcScoreConservation:
    def _setup_open_major(self):
        client = create_prospect_client(legal_name="Score Co",
                                        certification_scheme="HALAL")
        facility = create_facility_for(client["id"], name="SC Plant")
        visit = start_routine_visit(facility["id"], inspector_user_id="sup-1")
        finding = raise_finding(visit["id"], "sup-1", severity="MAJOR",
                                description="missing halal slaughter log",
                                remediation_deadline="2026-09-01T00:00:00Z")
        return client, facility, finding

    def test_nc_score_conserved_under_remediation_submit_and_verify_fail(
            self, api):
        """PRD section 3.6: "the score is recomputed because the finding has
        left the counted set." PRD section 3.6: "the finding returns to
        `REOPENED`, its `remediation_deadline` is replaced, and the score
        recomputes upward by the finding's weight as it re-enters the counted
        set."

        Design: Difficulty/compensating_invariant/nc_score_conserved_under_remediation_submit_and_verify_fail
        """
        client, _facility, finding = self._setup_open_major()
        cc = make_client_contact_headers(client["id"])
        before = get_client(client["id"])
        assert before["open_nc_score"] == 3 and before["risk_tier"] == "MEDIUM"

        submitted = validate_success(
            api.submit_remediation(finding["id"],
                                   "logs reconstructed and countersigned", cc))
        assert submitted["status"] == "REMEDIATION_SUBMITTED"
        mid = get_client(client["id"])
        assert mid["open_nc_score"] == 0 and mid["risk_tier"] == "LOW", (
            "REMEDIATION_SUBMITTED is excluded from the counted set")

        reopened = validate_success(api.verify_finding(
            finding["id"],
            {"outcome": "FAILED",
             "new_remediation_deadline": "2026-12-01T00:00:00Z"},
            make_supervisor_headers("sup-2")))
        assert reopened["status"] == "REOPENED"
        assert_instant_equals(reopened["remediation_deadline"],
                              "2026-12-01T00:00:00Z", "replaced deadline")
        after = get_client(client["id"])
        assert after["open_nc_score"] == before["open_nc_score"], (
            "submit + FAILED verify conserve the score exactly")
        assert after["risk_tier"] == before["risk_tier"] == "MEDIUM"

    def test_nc_score_unchanged_under_verify_closed(self, api):
        """PRD section 3.6: "Verifying with `outcome` `CLOSED` lands the finding
        in the terminal state `VERIFIED_CLOSED` — the score does not change on
        this transition because both `REMEDIATION_SUBMITTED` and
        `VERIFIED_CLOSED` are excluded from the counted set."

        Design: Difficulty/compensating_invariant/nc_score_conserved_under_remediation_submit_and_verify_fail
        """
        client, _facility, finding = self._setup_open_major()
        cc = make_client_contact_headers(client["id"])
        validate_success(api.submit_remediation(finding["id"], "done", cc))
        mid = get_client(client["id"])
        assert mid["open_nc_score"] == 0

        closed = validate_success(api.verify_finding(
            finding["id"], {"outcome": "CLOSED"},
            make_supervisor_headers("sup-2")))
        assert closed["status"] == "VERIFIED_CLOSED"
        after = get_client(client["id"])
        assert after["open_nc_score"] == 0 and after["risk_tier"] == "LOW", (
            "VERIFIED_CLOSED stays excluded from the counted set")


class TestRiskTierBoundary:
    def test_low_medium_tier_boundary_at_score_2_vs_3(self, api):
        """PRD section 3.6: "The client's `risk_tier` derives from the score:
        `LOW` when the score is at most 2, `MEDIUM` when it is from 3 through 7,
        and `HIGH` when it is 8 or more."

        Design: Corner/calculations/low_medium_tier_boundary_at_score_2_vs_3
        """
        client = create_prospect_client(legal_name="Tier Co",
                                        certification_scheme="HALAL")
        facility = create_facility_for(client["id"], name="FT")
        visit = start_routine_visit(facility["id"], inspector_user_id="sup-1",
                                    start="2026-08-02T09:00:00Z",
                                    end="2026-08-02T12:00:00Z",
                                    clock_into_window="2026-08-02T10:00:00Z")
        raise_finding(visit["id"], "sup-1", severity="MINOR", description="n1")
        raise_finding(visit["id"], "sup-1", severity="MINOR", description="n2")
        two = get_client(client["id"])
        assert two["open_nc_score"] == 2 and two["risk_tier"] == "LOW", (
            "score exactly 2 stays LOW (at-most-2 boundary)")

        raise_finding(visit["id"], "sup-1", severity="MINOR", description="n3")
        three = get_client(client["id"])
        assert three["open_nc_score"] == 3 and three["risk_tier"] == "MEDIUM", (
            "score exactly 3 engages MEDIUM (from-3 boundary)")


class TestEscalationSweep:
    def test_facility_suspension_cascade_via_finding_escalation_sweep(
            self, api, reviewer_headers):
        """PRD section 3.6: "when the clock sweep finds an `OPEN` or `REOPENED`
        finding whose deadline has passed, the finding becomes `ESCALATED` and
        fires the facility → certificate → client suspension cascade (without
        the equipment compromise that only physical access events and critical
        observations cause)."

        Design: Corner/calculations/facility_suspension_cascade_via_finding_escalation_sweep
        """
        ctx = setup_certified_client(legal_name="Esc Co")
        visit = start_routine_visit(ctx["facility"]["id"],
                                    inspector_user_id="sup-2",
                                    start="2026-08-10T09:00:00Z",
                                    end="2026-08-10T12:00:00Z",
                                    clock_into_window="2026-08-10T10:00:00Z")
        open_finding = raise_finding(
            visit["id"], "sup-2", severity="MAJOR", description="fnd1",
            remediation_deadline="2026-09-01T00:00:00Z")
        settled_finding = raise_finding(
            visit["id"], "sup-2", severity="MINOR", description="fnd2",
            remediation_deadline="2026-09-01T00:00:00Z")
        cc = make_client_contact_headers(ctx["client"]["id"])
        validate_success(api.submit_remediation(settled_finding["id"], "done",
                                                cc))

        set_clock("2026-09-02T00:00:00Z")
        escalated = validate_success(api.get_finding(open_finding["id"],
                                                     reviewer_headers))
        assert escalated["status"] == "ESCALATED", (
            "OPEN past deadline escalates on the sweep")
        settled = validate_success(api.get_finding(settled_finding["id"],
                                                   reviewer_headers))
        assert settled["status"] == "REMEDIATION_SUBMITTED", (
            "REMEDIATION_SUBMITTED findings are exempt from escalation")

        facility = validate_success(api.get_facility(ctx["facility"]["id"],
                                                     reviewer_headers))
        assert facility["status"] == "SUSPENDED"
        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    reviewer_headers))
        assert cert["status"] == "SUSPENDED"
        client = get_client(ctx["client"]["id"])
        assert client["status"] == "SUSPENDED"
        assert client["open_nc_score"] == 3, (
            "the ESCALATED MAJOR still counts; the settled MINOR does not")


class TestCriticalFindingCascade:
    def test_critical_finding_suspension_cascade_depth3(self, api,
                                                        reviewer_headers):
        """PRD section 3.6: "A `CRITICAL` finding raised manually fires the same
        cascade as a no-access declaration: an `APPROVED` hosting facility
        suspends, in-scope `ACTIVE` certificates suspend, the client recomputes,
        and all of the facility's equipment lines become `COMPROMISED`."

        Design: Difficulty/transitive_cascade/critical_finding_suspension_cascade_depth3
        """
        ctx = setup_certified_client(legal_name="Crit Co")
        visit = start_routine_visit(ctx["facility"]["id"],
                                    inspector_user_id="sup-2")
        finding = raise_finding(
            visit["id"], "sup-2", severity="CRITICAL",
            description="non-certified animal fat on shared line")
        assert finding["status"] == "OPEN"

        client = get_client(ctx["client"]["id"])
        assert client["open_nc_score"] == 8 and client["risk_tier"] == "HIGH"
        assert client["status"] == "SUSPENDED", (
            "zero remaining ACTIVE certificates suspends the client")
        facility = validate_success(api.get_facility(ctx["facility"]["id"],
                                                     reviewer_headers))
        assert facility["status"] == "SUSPENDED", (
            "facility suspension is caused by the CRITICAL finding")
        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    reviewer_headers))
        assert cert["status"] == "SUSPENDED", (
            "certificate suspension is caused by the facility suspension")
        line = validate_success(api.get_equipment_line(ctx["line"]["id"],
                                                       reviewer_headers))
        assert line["kosherization_state"] == "COMPROMISED"

    def test_major_finding_does_not_fire_the_cascade(self, api,
                                                     reviewer_headers):
        """PRD section 3.6: "A `CRITICAL` finding raised manually fires the same
        cascade as a no-access declaration". PRD section 3.6: "`MINOR` weighs 1,
        `MAJOR` weighs 3, `CRITICAL` weighs 8".

        Design: Difficulty/transitive_cascade/critical_finding_suspension_cascade_depth3
        """
        ctx = setup_certified_client(legal_name="Crit Co 2")
        visit = start_routine_visit(ctx["facility"]["id"],
                                    inspector_user_id="sup-2")
        finding = raise_finding(visit["id"], "sup-2", severity="MAJOR",
                                description="label mismatch")
        assert finding["status"] == "OPEN"

        client = get_client(ctx["client"]["id"])
        assert client["open_nc_score"] == 3 and client["risk_tier"] == "MEDIUM"
        facility = validate_success(api.get_facility(ctx["facility"]["id"],
                                                     reviewer_headers))
        assert facility["status"] == "APPROVED", (
            "a MAJOR finding is not a cascade trigger")
        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    reviewer_headers))
        assert cert["status"] == "ACTIVE"
        assert client["status"] == "CERTIFIED"
