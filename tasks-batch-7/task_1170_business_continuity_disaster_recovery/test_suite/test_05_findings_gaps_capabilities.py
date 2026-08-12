"""Findings, gaps, capabilities, and vendor continuity (PRD §3.4, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    complete_exercise,
    create_active_process,
    create_active_vendor,
    create_approved_bia,
    create_assessment,
    create_capability,
    create_completed_exercise,
    create_contact,
    create_exercise,
    create_gap,
    create_validated_capability,
    make_exercise_officer_headers,
    make_plan_author_headers,
    make_risk_committee_headers,
    make_vendor_manager_headers,
    record_validation_run,
    set_clock,
    setup_approved_program,
    start_exercise,
    validate_error,
    validate_success,
)


class TestFindingVerifyBacklogInvariant:
    def _setup(self):
        set_clock()
        author = create_contact("Author Ann", "Plan Author")
        committee = create_contact("Committee Kim", "Risk Committee")
        program = setup_approved_program(process_name="Custody", rto=8, rpo=2)
        process, plan = program["process"], program["plan"]
        exercise = create_completed_exercise(
            process["id"], plan["id"], committee["id"],
            completion_outcome="PARTIAL", achieved_rto_hours=8, achieved_rpo_hours=2,
            scheduled_start="2026-05-15T09:00:00Z",
            scheduled_end="2026-05-15T11:00:00Z")
        finding = validate_success(
            api_client.create_finding(
                {"exercise_id": exercise["id"], "process_id": process["id"],
                 "severity": "HIGH", "description": "call tree outdated",
                 "due_date": "2026-12-01T00:00:00Z"},
                make_exercise_officer_headers(committee["id"])),
            expected_status=201)
        return author, committee, process, finding

    def test_remediate_opens_exactly_one_backlog_gap(self, api):
        """PRD §3.6: "Remediation is a `PlanAuthor` action moving `OPEN` → `REMEDIATING`, and it auto-creates a remediation gap: `gap_type` `FINDING`, `finding_id` pointing at this finding, `capability_id` empty, `severity` and `due_date` copied from the finding, state `OPEN`; the finding's `version` increments."
        PRD §3.7: "Each gap in `OPEN` or `IN_PROGRESS` contributes a severity weight — 4 for `CRITICAL`, 3 for `HIGH`, 2 for `MEDIUM`, 1 for `LOW` — doubled when the gap is overdue under the strict reading above; `CLOSED` and `ACCEPTED_RISK` gaps contribute nothing."

        Finding creation adds no gap; remediate adds exactly one (HIGH, fresh: 3).

        Design: Difficulty/compensating_invariant/finding_verify_closes_gap_backlog_invariant
        """
        author, committee, process, finding = self._setup()
        author_headers = make_plan_author_headers(author["id"])
        before = validate_success(api_client.get_gap_pressure(process["id"], author_headers))
        assert before["pressure_score"] == 0 and before["open_gap_count"] == 0, (
            "finding creation itself adds no gap"
        )
        remediated = validate_success(
            api_client.remediate_finding(finding["id"], author_headers))
        assert remediated["status"] == "REMEDIATING"
        mid = validate_success(api_client.get_gap_pressure(process["id"], author_headers))
        assert mid["pressure_score"] == 3 and mid["open_gap_count"] == 1, (
            f"one fresh HIGH gap must read pressure 3 / open 1, got {mid}"
        )

    def test_verify_closes_gap_and_restores_backlog(self, api):
        """PRD §3.6: "Verification moves `REMEDIATING` → `VERIFIED`, records the acting contact in `verified_by_contact_id`, and closes the remediation gap: the gap whose `finding_id` is this finding moves to `CLOSED` with `closed_by_contact_id` set to the same acting contact, and that closure refreshes the gap-backlog aggregates — the process's overdue-gap flags recompute and every recovery capability of the process recomputes `validation_freshness`, with the gap's and each affected capability's `version` incrementing."

        Verify is the compensating action: the backlog returns to its pre-finding state.

        Design: Difficulty/compensating_invariant/finding_verify_closes_gap_backlog_invariant
        """
        author, committee, process, finding = self._setup()
        author_headers = make_plan_author_headers(author["id"])
        committee_headers = make_risk_committee_headers(committee["id"])
        validate_success(api_client.remediate_finding(finding["id"], author_headers))
        verified = validate_success(api_client.verify_finding(finding["id"], committee_headers))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_contact_id"] == committee["id"]
        after = validate_success(api_client.get_gap_pressure(process["id"], author_headers))
        assert after["pressure_score"] == 0 and after["open_gap_count"] == 0, (
            "verify must restore the pre-finding backlog"
        )
        gaps = validate_success(api_client.list_finding_gaps(finding["id"], committee_headers))
        assert len(gaps) == 1
        assert gaps[0]["status"] == "CLOSED"
        assert gaps[0]["closed_by_contact_id"] == committee["id"]


class TestGapPressureComputation:
    def test_gap_pressure_severity_weighting_and_critical_doubling(self, api):
        """PRD §3.7: "Each gap in `OPEN` or `IN_PROGRESS` contributes a severity weight — 4 for `CRITICAL`, 3 for `HIGH`, 2 for `MEDIUM`, 1 for `LOW` — doubled when the gap is overdue under the strict reading above; `CLOSED` and `ACCEPTED_RISK` gaps contribute nothing. The `pressure_score` is the sum of these contributions, and if any overdue gap has severity `CRITICAL`, the entire sum is then doubled."

        HIGH overdue + LOW fresh = 3*2 + 1 = 7; adding an overdue CRITICAL gives
        (7 + 4*2) * 2 = 30 — the doubler applies to the whole sum.

        Design: Corner/calculations/gap_pressure_severity_weighting_and_critical_doubling
        """
        set_clock()
        author = create_contact("Author Ann", "Author")
        process = create_active_process(author["id"], name="GapProc")
        author_headers = make_plan_author_headers(author["id"])
        create_gap(process["id"], author["id"], severity="HIGH",
                   due_date="2026-05-20T00:00:00Z", description="g1")
        create_gap(process["id"], author["id"], severity="LOW",
                   due_date="2026-12-01T00:00:00Z", description="g2")
        before = validate_success(api_client.get_gap_pressure(process["id"], author_headers))
        assert before["pressure_score"] == 7, (
            f"3*2 + 1*1 must be 7, got {before['pressure_score']}"
        )
        create_gap(process["id"], author["id"], severity="CRITICAL",
                   due_date="2026-05-20T00:00:00Z", description="g3")
        after = validate_success(api_client.get_gap_pressure(process["id"], author_headers))
        assert after["pressure_score"] == 30, (
            f"(7 + 4*2) * 2 must be 30, got {after['pressure_score']}"
        )
        assert after["open_gap_count"] == 3
        assert after["overdue_gap_count"] == 2


class TestVendorExitRemediationPath:
    def test_capability_exit_cascade_requires_remediation_path(self, api):
        """PRD §3.4: "More sharply, every recovery capability whose `capability_type` is `VENDOR_FAILOVER` and whose `capability_ref_id` points at the exiting vendor flips from `VALIDATED` to `GAP_IDENTIFIED` if it is currently `VALIDATED`, and each flip auto-creates a remediation gap: `gap_type` of `CAPABILITY`, the capability recorded in `capability_id`, severity `HIGH`, an auto-generated `description`, and a `due_date` ninety days from the exit moment."
        PRD §3.7: "A capability in `GAP_IDENTIFIED` can be marked remediated by a `PlanAuthor`, moving it to `REMEDIATED` — but only when every gap whose `capability_id` is this capability has reached a terminal state, `CLOSED` or `ACCEPTED_RISK`; open work blocks the transition with `ERR_CAPABILITY_HAS_OPEN_GAPS`."

        The exit cascade flips the validated capability; mark-remediated is refused
        while the auto-created gap is open and succeeds after the committee closes it.

        Design: Corner/cross_cutting_layers/capability_exit_cascade_requires_remediation_path
        """
        owner = create_contact("Victor Owner", "Vendor Owner")
        manager = create_contact("Manny Manager", "Vendor Manager")
        process = create_active_process(owner["id"], name="ExitProc")
        create_approved_bia(process["id"], manager["id"], rto_target_hours=8,
                            rpo_target_hours=2, impact_financial_per_hour=100)
        vendor = create_active_vendor(owner["id"], manager["id"], name="ExitVendor",
                                      service_category="Network",
                                      criticality_rating="CRITICAL")
        capability = create_capability(process["id"], manager["id"],
                                       capability_type="VENDOR_FAILOVER",
                                       capability_ref_id=vendor["id"])
        record_validation_run(capability["id"], manager["id"], 8, 2)
        manager_headers = make_vendor_manager_headers(manager["id"])
        author_headers = make_plan_author_headers(manager["id"])
        committee_headers = make_risk_committee_headers(manager["id"])

        exited = validate_success(api_client.exit_third_party(vendor["id"], manager_headers))
        assert exited["status"] == "EXITED"
        cap_after = validate_success(
            api_client.get_recovery_capability(capability["id"], manager_headers))
        assert cap_after["status"] == "GAP_IDENTIFIED", "the exit cascade must flip it"

        blocked = api_client.mark_capability_remediated(capability["id"], author_headers)
        validate_error(blocked, ApiErrorId.ERR_CAPABILITY_HAS_OPEN_GAPS)

        gaps = validate_success(api_client.list_capability_gaps(capability["id"], author_headers))
        assert len(gaps) == 1 and gaps[0]["severity"] == "HIGH"
        validate_success(api_client.close_gap(gaps[0]["id"], committee_headers))
        remediated = validate_success(
            api_client.mark_capability_remediated(capability["id"], author_headers))
        assert remediated["status"] == "REMEDIATED"


class TestFinalizeImmediateConsistency:
    def test_finalize_assessment_gap_visible_immediately(self, api):
        """PRD §2.6: "Wherever §3 says an action "recomputes" or "refreshes" a derived value, that refresh happens synchronously and its results are visible in the response and in every subsequent read."
        PRD §3.4: "When the finalized assessment's `meets_required_rto` is false, the server opens a remediation gap on the assessment's process: `gap_type` `CAPABILITY` with `capability_id` and `finding_id` both empty, severity `HIGH`, an auto-generated `description`, and a `due_date` ninety days out."

        ANNUAL, assessed 12/2 against the APPROVED analysis's 8/2: rto component
        100-(12-8)*10 = 60, rpo component 100, floor(0.6*60 + 0.4*100) = 76; the
        auto-created HIGH OPEN gap is visible in the very next read.

        Design: Corner/consistency_model/finalize_assessment_gap_visible_immediately
        """
        owner = create_contact("Victor Owner", "Vendor Owner")
        manager = create_contact("Manny Manager", "Vendor Manager")
        process = create_active_process(owner["id"], name="ImmProc")
        create_approved_bia(process["id"], manager["id"], rto_target_hours=8,
                            rpo_target_hours=2, impact_financial_per_hour=100)
        vendor = create_active_vendor(owner["id"], manager["id"], name="ImmVendor")
        assessment = create_assessment(
            vendor["id"], process["id"], manager["id"], assessment_type="ANNUAL",
            assessed_rto_hours=12, assessed_rpo_hours=2,
            rto_required_hours=6, rpo_required_hours=1)
        finalized = validate_success(
            api_client.finalize_assessment(
                assessment["id"], make_vendor_manager_headers(manager["id"])))
        assert finalized["status"] == "FINALIZED"
        assert finalized["continuity_score"] == 76, (
            f"floor(0.6*60 + 0.4*100) must be 76, got {finalized['continuity_score']}"
        )
        gaps = validate_success(
            api_client.list_gaps(make_vendor_manager_headers(manager["id"]),
                                 params={"process_id": process["id"]}))
        assert len(gaps) == 1
        assert gaps[0]["severity"] == "HIGH"
        assert gaps[0]["status"] == "OPEN"


class TestAssessmentFinalizeSod:
    def test_assessment_finalize_sod_against_vendor_owner(self, api):
        """PRD §3.4: "Finalization moves the assessment `DRAFT` → `FINALIZED` under three guards: the assessment must be `DRAFT` (`ERR_INVALID_STATE`), the referenced vendor must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`), and the acting contact must differ from the vendor's `owner_contact_id` (`ERR_SOD_VIOLATION`)."
        PRD §3.4: "The required targets are resolved from the process's latest `APPROVED` analysis — latest meaning the approval-ordered read, tie-broken by the analysis's `updated_at` most recent first and then `created_at` most recent first — and only when the process has no `APPROVED` analysis at all do the fallback inputs `rto_required_hours` and `rpo_required_hours` apply."

        The vendor owner cannot finalize; another manager finalizes at score 100
        under the fallback targets (no APPROVED analysis), and no gap opens.

        Design: Corner/rbac/assessment_finalize_sod_against_vendor_owner
        """
        owner = create_contact("Victor Owner", "Vendor Owner")
        manager = create_contact("Manny Manager", "Vendor Manager")
        process = create_active_process(owner["id"], name="SodProc")
        vendor = create_active_vendor(owner["id"], manager["id"], name="SodVendor")
        assessment = create_assessment(
            vendor["id"], process["id"], owner["id"], assessment_type="ANNUAL",
            assessed_rto_hours=4, assessed_rpo_hours=1,
            rto_required_hours=6, rpo_required_hours=2)
        sod = api_client.finalize_assessment(
            assessment["id"], make_vendor_manager_headers(owner["id"]))
        validate_error(sod, ApiErrorId.ERR_SOD_VIOLATION)

        finalized = validate_success(
            api_client.finalize_assessment(
                assessment["id"], make_vendor_manager_headers(manager["id"])))
        assert finalized["status"] == "FINALIZED"
        assert finalized["continuity_score"] == 100, (
            "assessed 4 <= required 6 and 1 <= 2 under the fallback targets"
        )
        assert finalized["meets_required_rto"] is True
        gaps = validate_success(
            api_client.list_gaps(make_vendor_manager_headers(manager["id"]),
                                 params={"process_id": process["id"]}))
        assert gaps == [], "no gap opens when the vendor meets the required RTO"
