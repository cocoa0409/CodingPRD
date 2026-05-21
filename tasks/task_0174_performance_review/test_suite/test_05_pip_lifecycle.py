"""PIPCase lifecycle: pass / fail / withdraw + ends_at gate + cascade
to CompPlan rejection on FAILED.
"""
from __future__ import annotations

from test_helpers import (
    TEST_USERS,
    advance_clock_past,
    create_comp_plan_payload,
    propose_plan,
    setup_active_pip_case,
    setup_draft_comp_plan,
    setup_finalized_review_case,
    validate_error,
    validate_success,
)


# ===========================================================================
# Pass / Fail / Withdraw branching from ACTIVE (PRD §3.6)
# ===========================================================================
class TestPipBranching:

    def test_withdraw_active_pip_returns_employee_to_active(self, api):
        """PRD §3.6: "The third option, withdrawal, is the inverse — it
        is permitted only while the clock has not yet reached
        `ends_at`; the subject's status flips from `ON_PIP` back to
        `ACTIVE`."

        # difficulty: non_linear_state_machine/pip_case_branching_pass_or_fail
        """
        bundle, pip = setup_active_pip_case("NEEDS_IMPROVEMENT")
        # PRD §3.6: withdraw requires clock_now() < ends_at — the clock
        # has not been advanced, so withdraw must succeed.
        upd = validate_success(api.withdraw_pip_case(
            bundle.cycle["id"], pip["id"], bundle.hrbp.headers,
        ), 200)
        assert upd["status"] == "WITHDRAWN"
        subj = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert subj["status"] == "ACTIVE"

    def test_pass_after_ends_at_returns_employee_to_active(self, api):
        """PRD §3.6: "Marking a PIP `PASSED` is permitted only after the
        logical clock has reached or passed `ends_at` (otherwise
        `ERR_PIP_NOT_ELAPSED`); the subject's `Employee.status` flips
        from `ON_PIP` back to `ACTIVE`, and an audit event is logged."

        # difficulty: non_linear_state_machine/pip_case_branching_pass_or_fail
        # difficulty: resource_temporal_overlap/pip_case_ends_at_gate
        """
        bundle, pip = setup_active_pip_case("NEEDS_IMPROVEMENT")
        # PRD §2.13 + §3.6: advance clock to ends_at (equality is on the
        # allowed side per "reached or passed").
        advance_clock_past(pip["ends_at"], seconds_after=1)
        upd = validate_success(api.pass_pip_case(
            bundle.cycle["id"], pip["id"], bundle.hrbp.headers,
        ), 200)
        assert upd["status"] == "PASSED"
        subj = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert subj["status"] == "ACTIVE"

    def test_fail_after_ends_at_terminates_employee(self, api):
        """PRD §3.6: "Marking a PIP `FAILED` is also permitted only
        after `ends_at` has elapsed; the subject's status flips from
        `ON_PIP` to `TERMINATED`...".

        # difficulty: non_linear_state_machine/pip_case_branching_pass_or_fail
        """
        bundle, pip = setup_active_pip_case("UNSATISFACTORY")
        advance_clock_past(pip["ends_at"], seconds_after=1)
        upd = validate_success(api.fail_pip_case(
            bundle.cycle["id"], pip["id"], bundle.hrbp.headers,
        ), 200)
        assert upd["status"] == "FAILED"
        subj = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert subj["status"] == "TERMINATED"


# ===========================================================================
# Ends_at temporal gate boundary (PRD §3.6, §2.13)
# ===========================================================================
class TestPipEndsAtGate:

    def test_pass_before_ends_at_rejected(self, api):
        """PRD §3.6: "Marking a PIP `PASSED` is permitted only after the
        logical clock has reached or passed `ends_at` (otherwise
        `ERR_PIP_NOT_ELAPSED`)".

        # difficulty: resource_temporal_overlap/pip_case_ends_at_gate
        """
        bundle, pip = setup_active_pip_case("NEEDS_IMPROVEMENT")
        # No clock advance — clock_now() < ends_at by default.
        res = api.pass_pip_case(
            bundle.cycle["id"], pip["id"], bundle.hrbp.headers,
        )
        validate_error(res, "ERR_PIP_NOT_ELAPSED")

    def test_fail_before_ends_at_rejected(self, api):
        """PRD §3.6: "Marking a PIP `FAILED` is also permitted only
        after `ends_at` has elapsed".

        # difficulty: resource_temporal_overlap/pip_case_ends_at_gate
        """
        bundle, pip = setup_active_pip_case("UNSATISFACTORY")
        res = api.fail_pip_case(
            bundle.cycle["id"], pip["id"], bundle.hrbp.headers,
        )
        validate_error(res, "ERR_PIP_NOT_ELAPSED")


# ===========================================================================
# Depth-2 cascade: PIP /fail -> CompPlan rejected (PRD §3.6)
# ===========================================================================
class TestPipFailCascadesCompPlan:

    def test_fail_cascades_proposed_comp_plan_to_rejected(self, api):
        """PRD §3.6: "the failure additionally cascades into
        compensation work: any `DRAFT` or `PROPOSED` `CompPlan` for
        that subject in this cycle automatically transitions to
        `REJECTED`."

        Depth-2 cascade.

        # difficulty: transitive_cascade/pip_fail_to_comp_plan_to_employee_terminate
        """
        # 1. Drive subj to ON_PIP via NI calibration; cycle now COMP_PLANNING.
        bundle, pip = setup_active_pip_case("NEEDS_IMPROVEMENT")
        # 2. Create a CompPlan for the subj (DRAFT) — promotion_to_level
        #    must not be set because subj is ON_PIP (PRD §3.7).
        plan = validate_success(api.create_comp_plan(
            bundle.cycle["id"],
            create_comp_plan_payload(bundle.subject["id"]),
            bundle.manager.headers,
        ), 201)
        # 3. Propose the plan: PRD §3.7 permits PROPOSED for ON_PIP
        #    subjects (merit will be 0 due to PIP gate).
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], plan["id"], bundle.manager.headers,
        ), 200)
        assert plan["status"] == "PROPOSED"
        # 4. Advance clock past pip.ends_at + fail the PIP.
        advance_clock_past(pip["ends_at"], seconds_after=1)
        validate_success(api.fail_pip_case(
            bundle.cycle["id"], pip["id"], bundle.hrbp.headers,
        ), 200)
        # 5. The PROPOSED plan must now be REJECTED.
        plan_after = validate_success(api.get_comp_plan(
            bundle.cycle["id"], plan["id"], bundle.manager.headers,
        ), 200)
        assert plan_after["status"] == "REJECTED"


# ===========================================================================
# PIP uniqueness (PRD §3.6)
# ===========================================================================
class TestPipUniqueness:

    def test_double_pip_for_same_subject_rejected(self, api):
        """PRD §3.6: "Each PIP is unique per `(cycle_id,
        subject_employee_id)`: a second creation attempt against the
        same pair is rejected with `ERR_PIP_ALREADY_EXISTS` and HTTP
        409."

        Setup: drive the same subject to two NI finalizations is
        forbidden by review-case uniqueness; we exercise the rule
        deterministically through PIP auto-creation racing. PRD does
        not expose an admin endpoint to manually re-create a PIP, but
        the same-cycle uniqueness is observable: an automatic PIPCase
        plus a withdraw, followed by ANOTHER NI finalization, is
        impossible because only one ReviewCase exists per (cycle,
        subject). We therefore verify the rule by attempting the
        post-withdraw scenario differently — by re-finalizing through a
        second department session (which is rejected upstream by the
        review-case unique-per-pair invariant). The simplest direct
        verification of the rule is the OR'd race form (covered in
        test_10_security_concurrency). For sequential coverage we
        confirm the auto-created PIPCase count remains 1 after the
        calibration commit, which is the deterministic guarantee a
        PRD-faithful implementer must produce."""
        # Just check there's exactly one PIPCase after a single NI
        # calibration commit — duplicate creation isn't reachable
        # through public endpoints, so this is the strongest
        # observable form of the unique-per-pair guarantee.
        bundle, pip = setup_active_pip_case("NEEDS_IMPROVEMENT")
        pips = validate_success(api.list_pip_cases(
            bundle.cycle["id"], bundle.hrbp.headers,
            params={"subject_employee_id": bundle.subject["id"]},
        ), 200)
        if isinstance(pips, dict):
            pips = pips.get("data", [])
        assert len(pips) == 1
