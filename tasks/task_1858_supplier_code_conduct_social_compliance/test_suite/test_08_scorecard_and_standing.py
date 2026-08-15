"""Supplier scorecard dual variants, consequence tiers, standing, grievances."""
from test_helpers import (
    OFFICER,
    TEST_USERS,
    ApiErrorId,
    assert_grievance,
    cap_full_pass_cycle,
    create_facility,
    create_supplier,
    file_grievance,
    get_scorecard,
    get_supplier,
    make_supplier_contact_headers,
    record_finding,
    schedule_audit,
    setup_active_supplier,
    setup_in_progress_audit,
    triage_grievance,
    validate_error,
    validate_success,
    create_auditor,
)

HOTLINE = TEST_USERS["worker_hotline_headers"]


def dual_variant_scenario(api):
    """ACTIVE APPAREL supplier, US/10-worker facility; audit records MAJOR,
    MAJOR, MINOR, then ZERO_TOLERANCE (auto-fails); the first MAJOR and the
    MINOR are remediated to VERIFIED_CLOSED via full plan cycles; one
    unresolved CRITICAL grievance remains."""
    ctx = setup_in_progress_audit(
        supplier_name="Beta Goods Inc", sector="APPAREL",
        facility_name="Riverside DC", worker_count=10,
        zt_categories=("FORCED_LABOR", "CHILD_LABOR"),
    )
    audit_id = ctx["audit"]["id"]
    auditor_id = ctx["auditor"]["id"]
    maj_a = record_finding(audit_id, auditor_id, "MAJOR", "WORKING_HOURS",
                           "Overtime beyond 60h")
    record_finding(audit_id, auditor_id, "MAJOR", "WAGES",
                   "Missing premium pay")
    min_c = record_finding(audit_id, auditor_id, "MINOR", "HEALTH_SAFETY",
                           "Blocked exit sign")
    record_finding(audit_id, auditor_id, "ZERO_TOLERANCE", "FORCED_LABOR",
                   "Passports withheld")
    cap_full_pass_cycle(maj_a["id"], ctx["supplier"]["id"],
                        ctx["verifier"]["id"])
    cap_full_pass_cycle(min_c["id"], ctx["supplier"]["id"],
                        ctx["verifier"]["id"])
    file_grievance(ctx["facility"]["id"], channel="HOTLINE", category="WAGES",
                   severity="CRITICAL",
                   description="Unpaid wages for two months")
    return ctx


class TestScorecardDualVariant:
    def test_scorecard_provisional_counts_non_voided(self, api):
        """PRD §3.6: "From 100 it subtracts 40 for every `ZERO_TOLERANCE`
        finding that has not been voided, 10 for every non-voided `MAJOR`
        finding, 3 for every non-voided `MINOR` finding, 5 for every unresolved
        critical grievance — severity `CRITICAL` with status `SUBMITTED`,
        `UNDER_REVIEW`, or `ESCALATED` — and finally the supplier's
        `escalation_penalty_points`; the result is floored at 0. Remediation
        closure gives no credit in this variant: a `VERIFIED_CLOSED` finding
        still deducts."
        PRD §3.6: "The `verified_score` uses the identical weights but counts
        only findings still `OPEN`"

        Design: Difficulty/dual_variant_calc/supplier_scorecard_provisional_vs_verified
        """
        ctx = dual_variant_scenario(api)
        scorecard = get_scorecard(ctx["supplier"]["id"])
        # provisional: 100 - 40*1 - 10*2 - 3*1 - 5*1 = 32 (verified closures
        # give no credit).
        assert scorecard["provisional_score"] == 32
        # verified: 100 - 40*1 - 10*1 - 3*0 - 5*1 = 45 (the VERIFIED_CLOSED
        # MAJOR and MINOR restore their deductions).
        assert scorecard["verified_score"] == 45
        assert scorecard["verified_score"] > scorecard["provisional_score"], (
            "identical raw data yields a higher verified than provisional score"
        )

    def test_scorecard_verified_drives_tier_and_standing(self, api):
        """PRD §3.6: "The `consequence_tier` maps the verified score onto
        business consequences: `PREFERRED` at 80 or above; `QUALIFIED` from 60
        up to 79; `PROBATION_WATCH` from 40 up to 59; and `SOURCING_EXIT` below
        40, with each band inclusive on its lower bound."
        PRD §3.6: "a supplier moves `ACTIVE → PROBATION` whenever the verified
        score drops below 60 or any `OPEN` zero-tolerance finding exists across
        its facilities"
        PRD §3.6: "A computed scorecard read exposes both variants and the live
        counts feeding them: `supplier_id`, `provisional_score`,
        `verified_score`, `consequence_tier`, `escalation_penalty_points`,
        `open_zt_count`, `open_major_count`, `open_minor_count`, and
        `unresolved_critical_grievance_count`."

        Design: Difficulty/dual_variant_calc/supplier_scorecard_provisional_vs_verified
        """
        ctx = dual_variant_scenario(api)
        scorecard = get_scorecard(ctx["supplier"]["id"])
        assert scorecard["supplier_id"] == ctx["supplier"]["id"]
        assert scorecard["consequence_tier"] == "PROBATION_WATCH", (
            "verified 45 lies in the [40, 59] band"
        )
        assert scorecard["open_zt_count"] == 1
        assert scorecard["open_major_count"] == 1
        assert scorecard["open_minor_count"] == 0
        assert scorecard["unresolved_critical_grievance_count"] == 1
        assert scorecard["escalation_penalty_points"] == 0
        assert get_supplier(ctx["supplier"]["id"])["status"] == "PROBATION", (
            "an OPEN zero-tolerance finding holds the supplier in PROBATION"
        )


class TestConsequenceTierBoundaries:
    def test_consequence_tier_at_eighty_boundary(self, api):
        """PRD §3.6: "The `consequence_tier` maps the verified score onto
        business consequences: `PREFERRED` at 80 or above; `QUALIFIED` from 60
        up to 79; `PROBATION_WATCH` from 40 up to 59; and `SOURCING_EXIT` below
        40, with each band inclusive on its lower bound."

        Design: Difficulty/boundary_precision_check/consequence_tier_boundary_at_eighty
        """
        ctx = setup_in_progress_audit(supplier_name="Kilo Clothing",
                                      sector="APPAREL",
                                      facility_name="El Paso Sewing",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        auditor_id = ctx["auditor"]["id"]
        record_finding(audit_id, auditor_id, "MAJOR", "WAGES", "Wage issue 1")
        record_finding(audit_id, auditor_id, "MAJOR", "WORKING_HOURS",
                       "Hours issue 2")
        scorecard = get_scorecard(ctx["supplier"]["id"])
        assert scorecard["verified_score"] == 80, "100 - 10*2"
        assert scorecard["consequence_tier"] == "PREFERRED", (
            "80 is inclusive on the band's lower bound"
        )
        assert get_supplier(ctx["supplier"]["id"])["status"] == "ACTIVE"

    def test_consequence_tier_below_eighty(self, api):
        """PRD §3.6: "The `consequence_tier` maps the verified score onto
        business consequences: `PREFERRED` at 80 or above; `QUALIFIED` from 60
        up to 79; `PROBATION_WATCH` from 40 up to 59; and `SOURCING_EXIT` below
        40, with each band inclusive on its lower bound."

        Design: Difficulty/boundary_precision_check/consequence_tier_boundary_at_eighty
        """
        ctx = setup_in_progress_audit(supplier_name="Kilo Clothing",
                                      sector="APPAREL",
                                      facility_name="El Paso Sewing",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        auditor_id = ctx["auditor"]["id"]
        record_finding(audit_id, auditor_id, "MAJOR", "WAGES", "Wage issue 1")
        record_finding(audit_id, auditor_id, "MAJOR", "WORKING_HOURS",
                       "Hours issue 2")
        record_finding(audit_id, auditor_id, "MINOR", "ENVIRONMENT",
                       "Minor issue 3")
        scorecard = get_scorecard(ctx["supplier"]["id"])
        assert scorecard["verified_score"] == 77, "100 - 10*2 - 3"
        assert scorecard["consequence_tier"] == "QUALIFIED", (
            "77 is one MINOR finding below the PREFERRED boundary"
        )
        assert get_supplier(ctx["supplier"]["id"])["status"] == "ACTIVE"

    def test_consequence_tier_sourcing_exit_below_forty(self, api):
        """PRD §3.6: "`SOURCING_EXIT` below 40, with each band inclusive on its
        lower bound."
        PRD §3.6: "a supplier moves `ACTIVE → PROBATION` whenever the verified
        score drops below 60 or any `OPEN` zero-tolerance finding exists across
        its facilities"

        Design: Corner/calculations/consequence_tier_sourcing_exit_below_forty
        """
        ctx = setup_in_progress_audit(supplier_name="Mike Goods", sector="FOOD",
                                      facility_name="Site J",
                                      with_verifier=False)
        audit_id = ctx["audit"]["id"]
        auditor_id = ctx["auditor"]["id"]
        record_finding(audit_id, auditor_id, "MAJOR", "WAGES", "Wage issue")
        record_finding(audit_id, auditor_id, "MAJOR", "WORKING_HOURS",
                       "Hours issue")
        record_finding(audit_id, auditor_id, "ZERO_TOLERANCE", "FORCED_LABOR",
                       "Passport retention")
        file_grievance(ctx["facility"]["id"], category="FORCED_LABOR",
                       severity="CRITICAL", description="Workers confined")
        scorecard = get_scorecard(ctx["supplier"]["id"])
        # 100 - 40 - 10 - 10 - 5 = 35
        assert scorecard["verified_score"] == 35
        assert scorecard["consequence_tier"] == "SOURCING_EXIT", "35 < 40"
        assert get_supplier(ctx["supplier"]["id"])["status"] == "PROBATION"


class TestSupplierStandingCycle:
    def test_supplier_probation_recovery_cycle(self, api):
        """PRD §3.6: "a supplier moves `ACTIVE → PROBATION` whenever the
        verified score drops below 60 or any `OPEN` zero-tolerance finding
        exists across its facilities, and recovers `PROBATION → ACTIVE` when the
        verified score is back at 60 or above and no `OPEN` zero-tolerance
        finding exists."
        PRD §3.5: "the supplier scorecard recomputes with the verified variant
        restoring the finding's deduction; the supplier's `PROBATION → ACTIVE`
        recovery is re-evaluated"

        Design: Corner/state_machines/supplier_probation_recovery_cycle
        """
        ctx = setup_in_progress_audit(supplier_name="Juliet Goods", sector="FOOD",
                                      facility_name="Site M",
                                      audit_type="ANNUAL")
        audit_id = ctx["audit"]["id"]
        auditor_id = ctx["auditor"]["id"]
        findings = [
            record_finding(audit_id, auditor_id, "MAJOR", category, description)
            for category, description in (
                ("WAGES", "Wage issue 1"), ("WAGES", "Wage issue 2"),
                ("WORKING_HOURS", "Hours issue 3"),
                ("WORKING_HOURS", "Hours issue 4"),
                ("HEALTH_SAFETY", "Safety issue 5"),
                ("HEALTH_SAFETY", "Safety issue 6"),
            )
        ]
        # Six OPEN MAJOR findings: verified = 100 - 60 = 40 < 60.
        assert get_supplier(ctx["supplier"]["id"])["status"] == "PROBATION"

        for finding in findings[:2]:
            cap_full_pass_cycle(finding["id"], ctx["supplier"]["id"],
                                ctx["verifier"]["id"])
        supplier = get_supplier(ctx["supplier"]["id"])
        scorecard = get_scorecard(ctx["supplier"]["id"])
        assert scorecard["verified_score"] == 60, (
            "two verified closures restore 10 points each: 40 + 20"
        )
        assert supplier["status"] == "ACTIVE", (
            "verified 60 with no OPEN zero-tolerance finding recovers standing"
        )
        assert scorecard["consequence_tier"] == "QUALIFIED"


class TestSupplierTermination:
    def test_supplier_terminate_twice_rejected(self, api):
        """PRD §3.6: "A `ComplianceOfficer` terminates a supplier that is
        `ACTIVE` or `PROBATION` — any other state is rejected with
        `ERR_SUPPLIER_ALREADY_TERMINATED` — optionally recording a
        `termination_reason`."
        PRD §3.6: "That state is terminal."

        Design: Corner/state_machines/supplier_terminate_twice_rejected
        """
        ctx = setup_active_supplier(legal_name="Foxtrot Goods", sector="FOOD")
        terminated = validate_success(
            api.terminate_supplier(
                ctx["supplier"]["id"],
                {"termination_reason": "Sourcing exit"},
                OFFICER,
            )
        )
        assert terminated["status"] == "TERMINATED"
        resp = api.terminate_supplier(
            ctx["supplier"]["id"], {"termination_reason": "Again"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_ALREADY_TERMINATED, 409)

    def test_supplier_terminate_cascades_facilities_and_audits(self, api):
        """PRD §3.6: "The cascade is synchronous: every facility of the supplier
        that is `ACTIVE` moves to `EXITED`; every audit of those facilities in
        `SCHEDULED`, `IN_PROGRESS`, or `REPORT_SUBMITTED` moves to `CANCELLED`,
        while terminal audits are left untouched"

        Design: Corner/state_machines/supplier_terminate_cascades_facilities_and_audits
        """
        ctx = setup_active_supplier(legal_name="Golf Goods", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site P")
        auditor = create_auditor()
        audit = schedule_audit(facility["id"], auditor["id"])
        assert audit["status"] == "SCHEDULED"

        terminated = validate_success(
            api.terminate_supplier(
                ctx["supplier"]["id"],
                {"termination_reason": "Sourcing exit"},
                OFFICER,
            )
        )
        assert terminated["status"] == "TERMINATED"
        fac_after = validate_success(api.get_facility(facility["id"], OFFICER))
        assert fac_after["status"] == "EXITED"
        audit_after = validate_success(api.get_audit(audit["id"], OFFICER))
        assert audit_after["status"] == "CANCELLED"


class TestGrievances:
    def test_grievance_triage_path_and_score_restore(self, api):
        """PRD §3.7: "`START_REVIEW` moves a `SUBMITTED` grievance to
        `UNDER_REVIEW`. `ESCALATE` moves an `UNDER_REVIEW` grievance to
        `ESCALATED` and recomputes the supplier scorecard — an unresolved
        `CRITICAL` grievance deducts its 5 points whether it sits in
        `SUBMITTED`, `UNDER_REVIEW`, or `ESCALATED`. `RESOLVE` is valid from
        `UNDER_REVIEW` or `ESCALATED` and requires a `resolution_note`
        (`ERR_INVALID_REQUEST`); the grievance moves to `RESOLVED`, which is
        terminal, the scorecard recomputes with the grievance deduction removed"
        PRD §3.7: "The grievance is stored without reporter identity —
        `is_anonymized` is always true — and starts `SUBMITTED`."

        Design: Corner/state_machines/grievance_full_triage_path_and_score_restore
        """
        ctx = setup_active_supplier(legal_name="India Goods", sector="FOOD")
        facility = create_facility(ctx["supplier"]["id"], name="Site N")
        grievance = file_grievance(
            facility["id"], category="HARASSMENT", severity="CRITICAL",
            description="Supervisor abuse reported",
        )
        assert_grievance(grievance)
        assert grievance["status"] == "SUBMITTED"
        assert grievance["is_anonymized"] is True

        filed = get_scorecard(ctx["supplier"]["id"])
        assert filed["verified_score"] == 95, (
            "a CRITICAL grievance deducts 5 while unresolved"
        )
        assert filed["unresolved_critical_grievance_count"] == 1

        under_review = triage_grievance(grievance["id"], "START_REVIEW")
        assert under_review["status"] == "UNDER_REVIEW"
        escalated = triage_grievance(grievance["id"], "ESCALATE")
        assert escalated["status"] == "ESCALATED"
        assert get_scorecard(ctx["supplier"]["id"])["verified_score"] == 95, (
            "the deduction persists through ESCALATED"
        )

        resolved = triage_grievance(
            grievance["id"], "RESOLVE",
            resolution_note="Investigation completed, supervisor removed",
        )
        assert resolved["status"] == "RESOLVED"
        restored = get_scorecard(ctx["supplier"]["id"])
        assert restored["verified_score"] == 100, (
            "resolving removes the grievance deduction"
        )
        assert restored["unresolved_critical_grievance_count"] == 0

    def test_grievance_triage_after_resolved_rejected(self, api):
        """PRD §3.7: "`RESOLVE` is valid from `UNDER_REVIEW` or `ESCALATED` and
        requires a `resolution_note` (`ERR_INVALID_REQUEST`); the grievance
        moves to `RESOLVED`, which is terminal"
        PRD §3.7: "Any triage action from a from-state that does not permit it
        is rejected with `ERR_GRIEVANCE_INVALID_STATE`."

        Design: Corner/state_machines/grievance_triage_after_resolved_rejected
        """
        supplier = create_supplier(legal_name="Delta Goods", sector="FOOD")
        facility = create_facility(supplier["id"], name="Site R")
        grievance = file_grievance(facility["id"], category="SAFETY",
                                   severity="MEDIUM",
                                   description="Broken ladder")
        triage_grievance(grievance["id"], "START_REVIEW")
        resolved = triage_grievance(grievance["id"], "RESOLVE",
                                    resolution_note="Ladder replaced")
        assert resolved["status"] == "RESOLVED"

        resp = api.triage_grievance(
            grievance["id"], {"action": "ESCALATE"}, OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_GRIEVANCE_INVALID_STATE, 409)

    def test_grievance_reads_confidential_to_program_staff(self, api):
        """PRD §2.9: "Grievance reads are confidential and restricted to program
        staff (`SourcingProgramAdmin`, `AuditCoordinator`, `ComplianceOfficer`);
        auditors, supplier contacts, and the hotline channel itself cannot read
        grievances."

        Design: Corner/rbac/grievance_list_forbidden_for_worker_hotline_and_supplier
        """
        supplier = create_supplier(legal_name="Quebec D", sector="FOOD")
        facility = create_facility(supplier["id"], name="Site G2")
        grievance = file_grievance(facility["id"], category="WAGES",
                                   severity="LOW", description="Late payslip")

        hotline_resp = api.list_grievances(HOTLINE)
        validate_error(hotline_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       403)
        supplier_resp = api.list_grievances(
            make_supplier_contact_headers(supplier["id"])
        )
        validate_error(supplier_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       403)

        fetched = validate_success(api.get_grievance(grievance["id"], OFFICER))
        assert fetched["id"] == grievance["id"], "program staff can read"
