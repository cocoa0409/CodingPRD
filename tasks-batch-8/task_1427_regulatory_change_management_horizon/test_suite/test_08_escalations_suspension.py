"""Escalations, owner suspension, and the deadline-breach cascade."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    confirm_gap,
    create_assessment,
    create_business_owner,
    create_change,
    create_obligation,
    create_plan,
    create_triaged_change,
    get_owner,
    get_plan,
    list_escalations,
    list_gaps_for_assessment,
    list_gaps_for_obligation,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    set_clock,
    setup_plan,
    start_assessment,
    submit_assessment,
    triage_change,
    validate_error,
    validate_success,
    MANAGER_1,
    OFFICER_A,
    api_client,
)


class TestDeadlineBreachCascade:
    def _breach_pipeline(self, citation):
        """IN_EXECUTION CRITICAL plan targeting 2026-08-10; no mappings, so the
        accept also fired one ZERO_COVERAGE escalation on the obligation."""
        return setup_plan(
            target_status="IN_EXECUTION", target="2026-08-10T00:00:00Z",
            citation=citation, criticality="CRITICAL",
        )

    def test_breach_mutates_plan_and_spawns_escalation(self, api):
        """PRD §3.6: "Crossing into `OVERDUE` — whether from `ON_TRACK` or from
        `AT_RISK` — spawns a deadline-breach escalation whenever the plan does
        not already have one standing in `OPEN` or `ACKNOWLEDGED`: `target_type`
        `IMPLEMENTATION_PLAN`, `trigger_rule` `DEADLINE_BREACH`, the plan's
        `business_owner_id` attached, `level` 1, status `OPEN`, and `opened_at`
        set to the clock."

        Design: Difficulty/transitive_cascade/tc_deadline_breach_suspension_chain
        """
        pipe = self._breach_pipeline("TC-1")
        plan, owner = pipe["plan"], pipe["owner"]
        set_clock("2026-08-20T00:00:00Z")
        assert get_plan(plan["id"])["deadline_posture"] == "OVERDUE"
        breaches = [
            e for e in list_escalations({"target_id": plan["id"], "status": "OPEN"})
            if e["trigger_rule"] == "DEADLINE_BREACH"
        ]
        assert len(breaches) == 1, f"Exactly one open breach per plan, got {len(breaches)}"
        assert breaches[0]["target_type"] == "IMPLEMENTATION_PLAN"
        assert breaches[0]["business_owner_id"] == owner["id"]
        assert breaches[0]["level"] == 1

    def test_breach_recomputes_owner_counters_below_threshold(self, api):
        """PRD §3.6: "That creation recomputes the owner's `open_escalation_count`,
        and at three or more the owner's `assignment_suspended` flips to true."
        PRD §3.9: "only the deadline-breach kind carries a `business_owner_id`;
        zero-coverage escalations have none."

        Design: Difficulty/transitive_cascade/tc_deadline_breach_suspension_chain
        """
        pipe = self._breach_pipeline("TC-1B")
        plan, owner, obl = pipe["plan"], pipe["owner"], pipe["obligation"]
        # The accept fired a ZERO_COVERAGE escalation on the (uncovered) CRITICAL obligation.
        zero_cov = [e for e in list_escalations({"target_id": obl["id"]}) if e["trigger_rule"] == "ZERO_COVERAGE"]
        assert len(zero_cov) == 1
        assert zero_cov[0]["business_owner_id"] is None

        set_clock("2026-08-20T00:00:00Z")
        owner_after = get_owner(owner["id"])
        assert owner_after["open_escalation_count"] == 1, "Ownerless zero-coverage escalation never enters the count"
        assert owner_after["assignment_suspended"] is False, "Threshold 3 not reached"


class TestOwnerSuspension:
    def _three_plan_pipeline(self):
        """One change, three ACTIVE CRITICAL obligations, one accepted
        assessment, three confirmed gaps, three IN_EXECUTION plans targeting
        2026-08-10, all owned by the same owner."""
        owner = create_business_owner()
        change = create_triaged_change(
            citation="OS-1", severity_hint="CRITICAL", feed_source="FED_REGISTER", regulator="CFPB"
        )
        obligations = [
            create_obligation(change["id"], obligation_code=f"OBL-OS-{i}", criticality="CRITICAL")
            for i in (1, 2, 3)
        ]
        assessment = create_assessment(change, owner["id"])
        start_assessment(assessment["id"], owner["id"])
        submit_assessment(assessment["id"], owner["id"], likelihood_score=4, severity_score=4)
        accept_assessment(assessment["id"])
        owner_headers = make_business_owner_headers(owner["id"])
        plans = []
        for obl in obligations:
            gap = confirm_gap(list_gaps_for_obligation(obl["id"])[0]["id"])
            plan = create_plan(gap["id"], owner["id"], target="2026-08-10T00:00:00Z", title=f"Plan {obl['id'][:8]}")
            api_client.submit_implementation_plan(plan["id"], owner_headers)
            api_client.approve_implementation_plan(plan["id"], make_manager_headers(MANAGER_1))
            begin = api_client.begin_execution_implementation_plan(plan["id"], owner_headers)
            assert begin.status_code == 200, f"Setup failed: {begin.text}"
            plans.append(plan)
        return owner, change, plans

    def _fresh_applicable_change(self):
        change = create_change(
            citation="OS-2", title="Follow-up change", feed_source="FED_REGISTER",
            regulator="CFPB", published_at="2026-08-18T00:00:00Z",
            effective_date="2027-01-01T00:00:00Z", severity_hint="MEDIUM",
        )
        return triage_change(change["id"], verdict="APPLICABLE", actor="officer-b")

    def test_three_breaches_suspend_owner(self, api, officer_a_headers):
        """PRD §3.4: "Assignment is also gated on the assignee's standing: when an
        owner's `open_escalation_count` has reached three or more, their
        `assignment_suspended` flag is true and any new assignment to them is
        rejected with `ERR_OWNER_SUSPENDED` (403)."

        Design: Corner/errors/err_owner_suspended_after_three_breaches
        """
        owner, _change, plans = self._three_plan_pipeline()
        set_clock("2026-08-20T00:00:00Z")
        for plan in plans:
            assert get_plan(plan["id"])["deadline_posture"] == "OVERDUE"
        owner_after = get_owner(owner["id"])
        assert owner_after["open_escalation_count"] == 3
        assert owner_after["assignment_suspended"] is True

        change2 = self._fresh_applicable_change()
        resp = api.create_impact_assessment(
            {
                "regulatory_change_id": change2["id"],
                "business_owner_id": owner["id"],
                "due_date": "2026-09-01T00:00:00Z",
                "expected_regulatory_change_version": change2["version"],
            },
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_SUSPENDED)

    def test_resolving_one_escalation_clears_suspension(self, api, officer_a_headers, manager_1_headers):
        """PRD §3.9: "Either flavor of resolution recomputes the affected owner's
        `open_escalation_count`, and `assignment_suspended` flips back to false
        the moment the count drops below three — restoring the owner's
        eligibility for new assessment assignments."
        PRD §3.9: "resolves one from either `OPEN` or `ACKNOWLEDGED` by supplying
        a `resolution_note`; resolution is terminal, moving the escalation to
        `RESOLVED`, and manual resolution stamps `resolution_code`
        `MANUAL_RESOLUTION` and `resolved_at` from the clock."

        Design: Corner/errors/err_owner_suspended_after_three_breaches
        """
        owner, _change, _plans = self._three_plan_pipeline()
        set_clock("2026-08-20T00:00:00Z")
        assert get_owner(owner["id"])["assignment_suspended"] is True

        open_breaches = list_escalations({"business_owner_id": owner["id"], "status": "OPEN"})
        assert len(open_breaches) == 3
        resp = api.resolve_escalation(
            open_breaches[0]["id"], {"resolution_note": "Deadline renegotiated with regulator"},
            manager_1_headers,
        )
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_code"] == "MANUAL_RESOLUTION"
        owner_after = get_owner(owner["id"])
        assert owner_after["open_escalation_count"] == 2
        assert owner_after["assignment_suspended"] is False

        change2 = self._fresh_applicable_change()
        resp = api.create_impact_assessment(
            {
                "regulatory_change_id": change2["id"],
                "business_owner_id": owner["id"],
                "due_date": "2026-09-01T00:00:00Z",
                "expected_regulatory_change_version": change2["version"],
            },
            officer_a_headers,
        )
        validate_success(resp, 201)
