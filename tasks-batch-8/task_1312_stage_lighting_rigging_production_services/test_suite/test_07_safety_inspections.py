"""Safety inspection and show certification: per-type begin gates, the
re-inspection loop, and the FINAL pass that certifies the production."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_planning_production, setup_load_in_production,
    create_plot, add_rigging_point, submit_plot, approve_plot, submit_point_for_review,
    create_power_plan, submit_power_plan, approve_power_plan,
    create_inspection, begin_inspection, pass_inspection, transition_inspection,
    pass_inspection_type, get_production,
    make_safety_inspector_headers,
)

PM = TEST_USERS["production_manager_headers"]
SI1 = TEST_USERS["safety_inspector_headers"]


class TestReinspectionLoop:
    def test_safety_inspection_reinspection_loop(self, api):
        """PRD §3.7: "Re-inspection is a loop, not a new document: the `ProductionManager` reschedules (`FAILED` → `SCHEDULED`), which increments `attempt_no` by 1 and clears both `inspector_user_id` and `findings` for the next attempt."
        PRD §3.7: "A passing `FINAL` inspection fires the production's `LOAD_IN` → `SHOW_READY` transition automatically." (a RIGGING pass fires no such transition)

        Design: Difficulty/non_linear_state_machine/safety_inspection_reinspection_loop
        """
        ctx = setup_load_in_production()
        inspection = create_inspection(ctx["production"]["id"], "RIGGING")
        inspection = begin_inspection(inspection["id"], "si-1")
        inspection = transition_inspection(
            inspection["id"], {"to": "FAILED", "findings": "Secondary steel not safetied"},
            make_safety_inspector_headers("si-1"))
        assert inspection["status"] == "FAILED"
        assert inspection["attempt_no"] == 1
        inspection = transition_inspection(inspection["id"], {"to": "SCHEDULED"}, PM)
        assert inspection["status"] == "SCHEDULED"
        assert inspection["attempt_no"] == 2
        assert inspection.get("inspector_user_id") is None
        assert inspection.get("findings") is None
        inspection = begin_inspection(inspection["id"], "si-2")
        inspection = pass_inspection(inspection["id"], "si-2")
        assert inspection["status"] == "PASSED"
        assert get_production(ctx["production"]["id"])["status"] == "LOAD_IN", \
            "a RIGGING pass does not certify the show"

    def test_inspection_starts_at_attempt_one_and_fail_requires_findings(self, api):
        """PRD §3.7: "Each inspection starts `SCHEDULED` with `attempt_no` 1."
        PRD §3.7: "Failing an inspection (`IN_PROGRESS` → `FAILED`) requires the inspector's `findings` text in the payload (its absence is `ERR_INVALID_REQUEST`)."

        Design: Difficulty/non_linear_state_machine/safety_inspection_reinspection_loop
        """
        ctx = setup_load_in_production()
        inspection = create_inspection(ctx["production"]["id"], "RIGGING")
        assert inspection["status"] == "SCHEDULED"
        assert inspection["attempt_no"] == 1
        begin_inspection(inspection["id"], "si-1")
        resp = api.transition_inspection(inspection["id"], {"to": "FAILED"}, SI1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data = transition_inspection(
            inspection["id"], {"to": "FAILED", "findings": "Trim chain frayed"}, SI1)
        assert data["status"] == "FAILED"


class TestElectricalInspectionGate:
    def test_electrical_inspection_requires_approved_plan(self, api):
        """PRD §3.7: "An `ELECTRICAL` inspection requires the production to have an `APPROVED` power plan; otherwise `ERR_POWER_PLAN_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/electrical_inspection_requires_approved_plan
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"])  # stays DRAFT
        inspection = create_inspection(ctx["production"]["id"], "ELECTRICAL")
        resp = api.transition_inspection(inspection["id"], {"to": "IN_PROGRESS"}, SI1)
        validate_error(resp, ApiErrorId.ERR_POWER_PLAN_NOT_APPROVED)
        submit_power_plan(plan["id"])
        approve_power_plan(plan["id"])
        data = begin_inspection(inspection["id"], "si-1")
        assert data["status"] == "IN_PROGRESS"

    def test_rejected_power_plan_does_not_satisfy_electrical_gate(self, api):
        """PRD §3.7: "An `ELECTRICAL` inspection requires the production to have an `APPROVED` power plan; otherwise `ERR_POWER_PLAN_NOT_APPROVED` (HTTP 409)."
        PRD §3.4: "Rejection moves the plan to `REJECTED`."

        Design: Difficulty/cross_entity_state_dependency/electrical_inspection_requires_approved_plan
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"])
        submit_power_plan(plan["id"])
        validate_success(api.transition_power_plan(plan["id"], {"to": "REJECTED"}, SI1))
        inspection = create_inspection(ctx["production"]["id"], "ELECTRICAL")
        resp = api.transition_inspection(inspection["id"], {"to": "IN_PROGRESS"}, SI1)
        validate_error(resp, ApiErrorId.ERR_POWER_PLAN_NOT_APPROVED)


class TestFinalInspection:
    def test_final_inspection_pass_certifies_production(self, api):
        """PRD §3.7: "A passing `FINAL` inspection fires the production's `LOAD_IN` → `SHOW_READY` transition automatically."

        Design: Corner/state_machines/final_inspection_pass_certifies_production
        """
        ctx = setup_load_in_production()
        pass_inspection_type(ctx["production"]["id"], "RIGGING", "si-1")
        pass_inspection_type(ctx["production"]["id"], "ELECTRICAL", "si-1")
        final = create_inspection(ctx["production"]["id"], "FINAL")
        begin_inspection(final["id"], "si-1")
        data = pass_inspection(final["id"], "si-1")
        assert data["status"] == "PASSED"
        assert get_production(ctx["production"]["id"])["status"] == "SHOW_READY"

    def test_final_inspection_prerequisite_missing(self, api):
        """PRD §3.7: "A `FINAL` inspection requires the production to be in `LOAD_IN` (otherwise `ERR_INVALID_STATE`) and, in addition, requires the production's latest-attempt `RIGGING` and `ELECTRICAL` inspections to both be `PASSED` — the "latest attempt" of a type being the inspection of that type with the highest `attempt_no` — otherwise `ERR_PREREQUISITE_INSPECTION_MISSING` (HTTP 409)."

        Design: Corner/errors/final_inspection_prerequisite_missing
        """
        ctx = setup_load_in_production()
        final = create_inspection(ctx["production"]["id"], "FINAL")
        resp = api.transition_inspection(final["id"], {"to": "IN_PROGRESS"}, SI1)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_INSPECTION_MISSING)
        after = validate_success(api.get_inspection(final["id"], PM))
        assert after["status"] == "SCHEDULED"

    def test_rigging_inspection_without_approved_points(self, api):
        """PRD §3.7: "A `RIGGING` inspection requires every rigging point on the production's currently `APPROVED` plot to be `APPROVED`; otherwise the begin is rejected with `ERR_RIGGING_NOT_APPROVED` (HTTP 409)."

        Design: Corner/errors/rigging_inspection_without_approved_points
        """
        ctx = setup_planning_production()
        plot = create_plot(ctx["production"])
        point = add_rigging_point(plot["id"])
        submit_plot(plot["id"])
        approve_plot(plot["id"])
        submit_point_for_review(point["id"])  # UNDER_REVIEW, not APPROVED
        inspection = create_inspection(ctx["production"]["id"], "RIGGING")
        resp = api.transition_inspection(inspection["id"], {"to": "IN_PROGRESS"}, SI1)
        validate_error(resp, ApiErrorId.ERR_RIGGING_NOT_APPROVED)
