"""Corrective action plans: the effectiveness-check cycle with count-based
exit to FAILED, verification at the window boundary, segregation of duties,
and role exclusivity."""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    begin_cap_check,
    get_success_data,
    make_auditor_headers,
    make_compliance_headers,
    mark_cap_ineffective,
    setup_cap_active,
    setup_cap_in_check,
    setup_cap_proposed,
    validate_error,
    verify_cap,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]


class TestEffectivenessCycle:
    def test_first_two_ineffective_rounds_loop_back_to_active(self, api):
        """PRD §3.9: "Marking the plan ineffective instead increments
        `cycle_count` and loops the plan back to `ACTIVE` with
        `check_started_at` cleared to null — unless that increment brings
        `cycle_count` to three, the platform's maximum number of correction
        cycles, in which case the plan moves to `FAILED`."

        Design: Difficulty/non_linear_state_machine/cap_effectiveness_cycle_to_failed
        """
        ctx = setup_cap_active(proposer_user_id="co-1")
        cap_id = ctx["cap"]["id"]
        begin_cap_check(cap_id, "co-1")
        round1 = mark_cap_ineffective(cap_id, "ia-1")
        assert round1["status"] == "ACTIVE"
        assert round1["cycle_count"] == 1
        begin_cap_check(cap_id, "co-1")
        round2 = mark_cap_ineffective(cap_id, "ia-1")
        assert round2["status"] == "ACTIVE"
        assert round2["cycle_count"] == 2

    def test_third_ineffective_round_terminates_failed(self, api):
        """PRD §3.9: "unless that increment brings `cycle_count` to three, the
        platform's maximum number of correction cycles, in which case the plan
        moves to `FAILED`. Both `VERIFIED` and `FAILED` are terminal."

        Design: Difficulty/non_linear_state_machine/cap_effectiveness_cycle_to_failed
        """
        ctx = setup_cap_active(proposer_user_id="co-1")
        cap_id = ctx["cap"]["id"]
        for _ in range(2):
            begin_cap_check(cap_id, "co-1")
            mark_cap_ineffective(cap_id, "ia-1")
        begin_cap_check(cap_id, "co-1")
        round3 = mark_cap_ineffective(cap_id, "ia-1")
        assert round3["status"] == "FAILED"
        assert round3["cycle_count"] == 3


class TestVerification:
    def test_verify_succeeds_at_exact_window_boundary(self, api):
        """PRD §3.9: "the effectiveness window must have elapsed, meaning the
        logical now must be at least fourteen days past `check_started_at`,
        else `ERR_CAP_WINDOW_NOT_ELAPSED` (HTTP 409). Verification moves the
        plan to `VERIFIED` and records the verifier in `verified_by_user_id`."

        Design: Corner/state_machines/cap_verify_success_at_window_boundary
        """
        ctx = setup_cap_in_check(proposer_user_id="co-1")
        advance_clock("2026-08-15T00:00:00Z")
        verified = verify_cap(ctx["cap"]["id"], "ia-1")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "ia-1", (
            "The boundary timestamp is inclusive-eligible: exactly fourteen "
            "days after check_started_at satisfies the window")

    def test_verify_before_window_elapsed_rejected(self, api):
        """PRD §3.9: "the effectiveness window must have elapsed, meaning the
        logical now must be at least fourteen days past `check_started_at`,
        else `ERR_CAP_WINDOW_NOT_ELAPSED` (HTTP 409)."

        Design: Corner/validations/cap_window_not_elapsed_rejected
        """
        ctx = setup_cap_in_check(proposer_user_id="co-1")
        advance_clock("2026-08-10T00:00:00Z")
        resp = api.verify_plan(ctx["cap"]["id"], make_auditor_headers("ia-1"))
        validate_error(resp, ApiErrorId.ERR_CAP_WINDOW_NOT_ELAPSED)


class TestPlanRbac:
    def test_compliance_officer_cannot_verify_plan(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.9: "Judgment belongs to an `InternalAuditor`"

        Design: Corner/rbac/compliance_officer_cannot_verify_plan
        """
        ctx = setup_cap_in_check(proposer_user_id="co-1")
        advance_clock("2026-08-20T00:00:00Z")
        resp = api.verify_plan(ctx["cap"]["id"], make_compliance_headers("co-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_internal_auditor_cannot_activate_plan(self, api):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.9: "A `DepartmentDirector` activates it, moving `PROPOSED →
        ACTIVE`."

        Design: Corner/rbac/internal_auditor_cannot_activate_plan
        """
        ctx = setup_cap_proposed(proposer_user_id="co-1")
        resp = api.activate_plan(ctx["cap"]["id"], make_auditor_headers("ia-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        plan = get_success_data(api.get_corrective_action_plan(
            ctx["cap"]["id"], DIRECTOR))
        assert plan["status"] == "PROPOSED"
