"""Implementation plans: deadline mandates, posture axis, extensions, approve gates."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    confirm_gap,
    create_assessment,
    create_business_owner,
    create_obligation,
    create_plan,
    create_triaged_change,
    get_plan,
    list_escalations,
    list_gaps_for_assessment,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    set_clock,
    setup_accepted_assessment,
    setup_confirmed_gap,
    setup_plan,
    start_assessment,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    MANAGER_1,
    OFFICER_A,
    api_client,
)


def _two_criticality_gaps():
    """Two confirmed gaps: one CRITICAL-obligation gap, one HIGH-obligation gap,
    both confirmed at the default clock. Returns (owner, gap_critical, gap_high)."""
    owner = create_business_owner()

    change_c = create_triaged_change(
        citation="DVC-C", severity_hint="CRITICAL", feed_source="FED_REGISTER", regulator="CFPB"
    )
    create_obligation(change_c["id"], obligation_code="OBL-2026-C01", criticality="CRITICAL")
    ia_c = create_assessment(change_c, owner["id"])
    start_assessment(ia_c["id"], owner["id"])
    submit_assessment(ia_c["id"], owner["id"], likelihood_score=3, severity_score=3)
    accept_assessment(ia_c["id"])
    gap_c = confirm_gap(list_gaps_for_assessment(ia_c["id"])[0]["id"])

    change_h = create_triaged_change(
        citation="DVC-H", severity_hint="MEDIUM", feed_source="STATE_BULLETIN",
        jurisdiction="US-CA", regulator="DFPI",
    )
    create_obligation(change_h["id"], obligation_code="OBL-2026-H02", criticality="HIGH")
    ia_h = create_assessment(change_h, owner["id"])
    start_assessment(ia_h["id"], owner["id"])
    submit_assessment(ia_h["id"], owner["id"], likelihood_score=4, severity_score=4, affected_business_lines=2)
    accept_assessment(ia_h["id"])
    gap_h = confirm_gap(list_gaps_for_assessment(ia_h["id"])[0]["id"])
    return owner, gap_c, gap_h


class TestDeadlineMandateVariants:
    def test_critical_mandate_counts_calendar_days(self, api):
        """PRD §3.6: "Three worked anchors pin the convention: with a confirmation
        at 2026-08-01T00:00:00Z, a Saturday, a `CRITICAL` mandate of 15 calendar
        days lands on 2026-08-16T00:00:00Z, a `HIGH` mandate of 45 business days
        lands on 2026-10-02T00:00:00Z, and a `MEDIUM` mandate of 90 business days
        lands on 2026-12-08T00:00:00Z."
        PRD §3.6: "It must lie strictly after the current clock
        (`ERR_DEADLINE_IN_PAST`), and it must not exceed the mandated
        implementation deadline for the obligation's criticality
        (`ERR_DEADLINE_EXCEEDS_MANDATE`)."

        Design: Difficulty/dual_variant_calc/dvc_deadline_calendar_vs_business
        """
        owner, gap_c, _gap_h = _two_criticality_gaps()
        late = api.create_implementation_plan(
            {"gap_analysis_id": gap_c["id"], "title": "Plan A one day late",
             "target_completion_date": "2026-08-17T00:00:00Z"},
            make_business_owner_headers(owner["id"]),
        )
        validate_error(late, ApiErrorId.ERR_DEADLINE_EXCEEDS_MANDATE)
        ok = api.create_implementation_plan(
            {"gap_analysis_id": gap_c["id"], "title": "Plan A at mandate",
             "target_completion_date": "2026-08-16T00:00:00Z"},
            make_business_owner_headers(owner["id"]),
        )
        plan = validate_success(ok, 201)
        assert plan["execution_status"] == "DRAFT"

    def test_high_mandate_counts_business_days(self, api):
        """PRD §3.6: "`CRITICAL` mandates count calendar days and are never
        adjusted for weekends. `LOW`, `MEDIUM`, and `HIGH` mandates count business
        days only — Monday through Friday — starting from the day after the
        confirmation day, and when the landing day falls on a Saturday or Sunday
        it rolls forward to the next Monday."
        PRD §3.6: "a `HIGH` mandate of 45 business days lands on
        2026-10-02T00:00:00Z".

        Design: Difficulty/dual_variant_calc/dvc_deadline_calendar_vs_business
        """
        owner, _gap_c, gap_h = _two_criticality_gaps()
        late = api.create_implementation_plan(
            {"gap_analysis_id": gap_h["id"], "title": "Plan B one day late",
             "target_completion_date": "2026-10-03T00:00:00Z"},
            make_business_owner_headers(owner["id"]),
        )
        validate_error(late, ApiErrorId.ERR_DEADLINE_EXCEEDS_MANDATE)
        ok = api.create_implementation_plan(
            {"gap_analysis_id": gap_h["id"], "title": "Plan B at mandate",
             "target_completion_date": "2026-10-02T00:00:00Z"},
            make_business_owner_headers(owner["id"]),
        )
        plan = validate_success(ok, 201)
        assert plan["execution_status"] == "DRAFT"


class TestPlanApprovalLoop:
    def test_reject_resubmit_cycle(self, api, manager_1_headers):
        """PRD §3.6: "Submitting (`DRAFT` → `SUBMITTED`, and `REJECTED` →
        `SUBMITTED` for the resubmission cycle) is the owner's action and stamps
        `submitted_by_user_id`."
        PRD §3.6: "Rejection carries a `reason` and hands the plan back to the
        owner for revision and resubmission."

        Design: Corner/state_machines/sm_plan_reject_resubmit_cycle
        """
        pipe = setup_plan(target_status="SUBMITTED", citation="SM-5", criticality="CRITICAL")
        plan, owner = pipe["plan"], pipe["owner"]
        resp = api.reject_implementation_plan(plan["id"], {"reason": "Milestones unclear"}, manager_1_headers)
        rejected = validate_success(resp, 200)
        assert rejected["execution_status"] == "REJECTED"
        resp = api.submit_implementation_plan(plan["id"], make_business_owner_headers(owner["id"]))
        resubmitted = validate_success(resp, 200)
        assert resubmitted["execution_status"] == "SUBMITTED"

    def test_approve_draft_rejected(self, api, manager_1_headers):
        """PRD §3.6: "A `ComplianceManager` approves only a plan standing
        `SUBMITTED` — approving or rejecting in any other execution state is
        rejected with `ERR_PLAN_NOT_SUBMITTED`".

        Design: Corner/errors/err_plan_not_submitted_blocks_approve
        """
        pipe = setup_plan(target_status="DRAFT", citation="PS-1", criticality="CRITICAL")
        resp = api.approve_implementation_plan(pipe["plan"]["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_SUBMITTED)
        assert get_plan(pipe["plan"]["id"])["execution_status"] == "DRAFT"

    def test_plan_create_requires_confirmed_gap(self, api):
        """PRD §3.6: "The gap must be `CONFIRMED` (`ERR_GAP_NOT_CONFIRMED`)".

        Design: Corner/errors/err_gap_not_confirmed_blocks_plan
        """
        pipe = setup_accepted_assessment(citation="GN-1", criticality="CRITICAL")
        gap = pipe["gaps"][0]
        assert gap["status"] == "OPEN"
        resp = api.create_implementation_plan(
            {"gap_analysis_id": gap["id"], "title": "Too early",
             "target_completion_date": "2026-08-16T00:00:00Z"},
            make_business_owner_headers(pipe["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_GAP_NOT_CONFIRMED)

    def test_second_plan_for_gap_rejected(self, api):
        """PRD §3.6: "at most one non-terminal plan may exist per gap analysis
        (`ERR_PLAN_ALREADY_EXISTS`)".

        Design: Corner/errors/err_plan_already_exists_for_gap
        """
        pipe = setup_plan(target_status="DRAFT", citation="PA-1", criticality="CRITICAL")
        resp = api.create_implementation_plan(
            {"gap_analysis_id": pipe["gap"]["id"], "title": "Second",
             "target_completion_date": "2026-08-16T00:00:00Z"},
            make_business_owner_headers(pipe["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_EXISTS)


class TestApproveRequiresActiveObligation:
    def _retired_obligation_pipeline(self, citation):
        """Confirmed gap, then obligation retired, then plan created + submitted
        while the obligation stands RETIRED."""
        pipe = setup_confirmed_gap(citation=citation, criticality="CRITICAL")
        obl, gap, owner = pipe["obligation"], pipe["gap"], pipe["owner"]
        resp = api_client.retire_obligation(obl["id"], make_officer_headers(OFFICER_A))
        assert resp.status_code == 200, f"Setup failed (retire): {resp.text}"
        plan = create_plan(gap["id"], owner["id"], target="2026-08-16T00:00:00Z")
        resp = api_client.submit_implementation_plan(plan["id"], make_business_owner_headers(owner["id"]))
        assert resp.status_code == 200, f"Setup failed (submit): {resp.text}"
        pipe["plan"] = get_plan(plan["id"])
        return pipe

    def test_approve_blocked_while_obligation_retired(self, api, manager_1_headers):
        """PRD §3.6: "A `ComplianceManager` approves only a plan standing
        `SUBMITTED` — approving or rejecting in any other execution state is
        rejected with `ERR_PLAN_NOT_SUBMITTED` — and only while the underlying
        obligation is still `ACTIVE` (`ERR_OBLIGATION_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/ced_plan_approve_requires_active_obligation
        """
        pipe = self._retired_obligation_pipeline("CE-1")
        resp = api.approve_implementation_plan(pipe["plan"]["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_OBLIGATION_NOT_ACTIVE)
        assert get_plan(pipe["plan"]["id"])["execution_status"] == "SUBMITTED"

    def test_approve_succeeds_after_reinstate_and_pins_register(self, api, manager_1_headers, officer_a_headers):
        """PRD §3.6: "Approval pins the register: `pinned_register_version_number`,
        unset until this moment, captures the register's `current_version_number`,
        `approved_by_user_id` records the manager, and the deadline posture is
        recomputed."
        PRD §3.2: "Reinstatement (`RETIRED` → `ACTIVE`) takes a `rationale` and is
        always permitted from `RETIRED`".

        Design: Difficulty/cross_entity_state_dependency/ced_plan_approve_requires_active_obligation
        """
        pipe = self._retired_obligation_pipeline("CE-1B")
        resp = api.reinstate_obligation(
            pipe["obligation"]["id"], {"rationale": "Retirement was premature"}, officer_a_headers
        )
        assert validate_success(resp)["status"] == "ACTIVE"
        resp = api.approve_implementation_plan(pipe["plan"]["id"], manager_1_headers)
        approved = validate_success(resp, 200)
        assert approved["execution_status"] == "APPROVED"
        assert approved["pinned_register_version_number"] == 0, "No register version published yet"
        assert approved["approved_by_user_id"] == "manager-1"


class TestDeadlinePostureAxis:
    def test_posture_walks_with_clock_while_execution_status_holds(self, api):
        """PRD §3.6: "Measuring the remaining window from the current logical
        clock to the `target_completion_date`: when the remaining window is
        strictly negative the posture is `OVERDUE` — a plan sitting exactly at
        its deadline is not overdue; when the window is from zero up to and
        including 14 days the posture is `AT_RISK`; when it is more than 14 days
        the posture is `ON_TRACK`."
        PRD §3.6: "Posture is recomputed when the clock advances, when the plan is
        approved, and when its deadline is extended."

        Design: Difficulty/non_linear_state_machine/nsm_plan_parallel_dimensions
        """
        pipe = setup_plan(
            target_status="IN_EXECUTION", target="2026-08-16T00:00:00Z",
            citation="PD-1", criticality="CRITICAL",
        )
        plan = pipe["plan"]
        assert pipe["plan"]["deadline_posture"] == "ON_TRACK", "15 days remaining at approve"
        set_clock("2026-08-05T00:00:00Z")
        mid = get_plan(plan["id"])
        assert mid["deadline_posture"] == "AT_RISK", "11 days remaining"
        assert mid["execution_status"] == "IN_EXECUTION"
        set_clock("2026-08-17T00:00:00Z")
        late = get_plan(plan["id"])
        assert late["deadline_posture"] == "OVERDUE", "Past target"
        assert late["execution_status"] == "IN_EXECUTION", "Axes never block each other"
        breaches = [e for e in list_escalations({"target_id": plan["id"]}) if e["trigger_rule"] == "DEADLINE_BREACH"]
        assert len(breaches) == 1 and breaches[0]["status"] == "OPEN"

    def test_extension_recovers_posture_and_resolves_escalation(self, api):
        """PRD §3.6: "A granted extension updates `target_completion_date`,
        increments `extension_count`, and recomputes the posture: an `OVERDUE`
        plan recovers to `AT_RISK` when the new remaining window falls within the
        14-day band, or directly to `ON_TRACK` when it exceeds 14 days".
        PRD §3.6: "Granting an extension also resolves every `OPEN` or
        `ACKNOWLEDGED` deadline-breach escalation standing on the plan, stamping
        `resolution_code` `EXTENSION_GRANTED`".

        Design: Difficulty/non_linear_state_machine/nsm_plan_parallel_dimensions
        """
        pipe = setup_plan(
            target_status="IN_EXECUTION", target="2026-08-16T00:00:00Z",
            citation="PD-1E", criticality="CRITICAL",
        )
        plan, owner = pipe["plan"], pipe["owner"]
        set_clock("2026-08-17T00:00:00Z")
        resp = api.extend_deadline_implementation_plan(
            plan["id"],
            {"new_target_completion_date": "2026-08-31T00:00:00Z", "rationale": "Regulator granted relief"},
            make_business_owner_headers(owner["id"]),
        )
        extended = validate_success(resp, 200)
        assert extended["deadline_posture"] == "AT_RISK", "Exactly 14 days remaining is inclusive AT_RISK"
        assert extended["execution_status"] == "IN_EXECUTION"
        assert extended["extension_count"] == 1
        breaches = [e for e in list_escalations({"target_id": plan["id"]}) if e["trigger_rule"] == "DEADLINE_BREACH"]
        assert len(breaches) == 1
        assert breaches[0]["status"] == "RESOLVED"
        assert breaches[0]["resolution_code"] == "EXTENSION_GRANTED"


class TestExtensionRules:
    def test_extension_boundary_rules(self, api):
        """PRD §3.6: "Extensions are available only while the plan stands
        `APPROVED` or `IN_EXECUTION` (`ERR_INVALID_STATE` otherwise); each plan
        allows at most two, so a request arriving when `extension_count` already
        stands at two is rejected with `ERR_MAX_EXTENSIONS_REACHED`; and the new
        target must lie strictly after the current target and no more than 90
        days beyond it (`ERR_INVALID_EXTENSION`)."

        Design: Corner/validations/val_extension_boundary_rules
        """
        pipe = setup_plan(
            target_status="APPROVED", target="2026-08-16T00:00:00Z",
            citation="VE-1", criticality="CRITICAL",
        )
        plan, owner = pipe["plan"], pipe["owner"]
        owner_headers = make_business_owner_headers(owner["id"])

        backward = api.extend_deadline_implementation_plan(
            plan["id"], {"new_target_completion_date": "2026-08-15T00:00:00Z", "rationale": "backwards"},
            owner_headers,
        )
        validate_error(backward, ApiErrorId.ERR_INVALID_EXTENSION)

        first = api.extend_deadline_implementation_plan(
            plan["id"], {"new_target_completion_date": "2026-08-31T00:00:00Z", "rationale": "first"},
            owner_headers,
        )
        assert validate_success(first, 200)["extension_count"] == 1
        second = api.extend_deadline_implementation_plan(
            plan["id"], {"new_target_completion_date": "2026-09-30T00:00:00Z", "rationale": "second"},
            owner_headers,
        )
        assert validate_success(second, 200)["extension_count"] == 2
        third = api.extend_deadline_implementation_plan(
            plan["id"], {"new_target_completion_date": "2026-10-15T00:00:00Z", "rationale": "third"},
            owner_headers,
        )
        validate_error(third, ApiErrorId.ERR_MAX_EXTENSIONS_REACHED)
