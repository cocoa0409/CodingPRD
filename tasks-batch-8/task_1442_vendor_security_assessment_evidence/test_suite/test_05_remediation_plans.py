"""Remediation plans and exception conservation: accept/verify cascades,
compensation on rejection, and the state-vs-segregation ordering (PRD §3.6, §2.8, §2.9)."""
import pytest

from test_helpers import (
    ANALYST,
    ANALYST_1,
    ANALYST_2,
    ApiErrorId,
    contact_headers,
    get_success_data,
    setup_completed_plan,
    setup_proposed_plan,
    setup_remediation_cycle,
    setup_risk_acceptance_review_cycle,
    TEST_USERS,
    validate_error,
    validate_success,
)

APPROVER = TEST_USERS["security_approver_headers"]


def _plan(api, ctx, plan_id):
    plans = get_success_data(api.list_cycle_remediation_plans(ctx["cycle"]["id"], ANALYST))
    for plan in plans:
        if plan["id"] == plan_id:
            return plan
    raise AssertionError(f"Plan {plan_id} not found")


def _exception(api, exception_id):
    return get_success_data(api.get_exception(exception_id, ANALYST))


def _open_count(api, cycle_id):
    return get_success_data(api.get_cycle(cycle_id, ANALYST))["open_exception_count"]


class TestVerifyRejectCompensation:
    def test_verify_reject_returns_exceptions_to_open(self, api):
        """PRD §3.6: "A failed verification — invoked with `reject` set true — moves
        the plan to `REJECTED` and compensates by returning every linked exception
        to `OPEN`, leaving `open_exception_count` unchanged; plan and cycle versions
        increment accordingly."

        Design: Difficulty/non_linear_state_machine/remediation_plan_verify_reject_reopens_exceptions
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        plan, _acceptor = setup_completed_plan(ctx)
        rejected = validate_success(
            api.verify_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], {"reject": True}, ANALYST_2),
            200,
        )
        assert rejected["status"] == "REJECTED"
        exception = _exception(api, ctx["exceptions"][0]["id"])
        assert exception["status"] == "OPEN", "Compensation must revert the accept cascade"
        assert _open_count(api, ctx["cycle"]["id"]) == 1

    def test_verify_pass_closes_exceptions_and_decrements_count(self, api):
        """PRD §3.6: "A passing verification moves the plan `COMPLETED → VERIFIED`,
        stamps `verified_at`, and cascades: every linked exception moves to
        `CLOSED_REMEDIATED` with its `closure_reason` taken from the verification
        note, and the cycle's `open_exception_count` drops by the number of linked
        exceptions."

        Design: Difficulty/non_linear_state_machine/remediation_plan_verify_reject_reopens_exceptions
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        plan, _acceptor = setup_completed_plan(ctx)
        verified = validate_success(
            api.verify_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], {}, ANALYST_2), 200
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_at"] is not None
        exception = _exception(api, ctx["exceptions"][0]["id"])
        assert exception["status"] == "CLOSED_REMEDIATED"
        assert _open_count(api, ctx["cycle"]["id"]) == 0


class TestOpenExceptionCountConservation:
    def test_accept_moves_exceptions_without_changing_count(self, api):
        """PRD §3.6: "Acceptance records the analyst's `X-User-ID` in the plan's
        `approved_by` and moves every linked exception `OPEN → IN_REMEDIATION` — the
        exceptions are still open, so `open_exception_count` does not change."
        PRD §3.6: "Each new exception opens in `OPEN` status and raises the cycle's
        `open_exception_count` by one, bumping the cycle's `version`."

        Design: Difficulty/compensating_invariant/open_exception_count_conserved_across_plan_lifecycle
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM", "LOW"))
        assert ctx["cycle"]["open_exception_count"] == 2
        plan = setup_proposed_plan(ctx)
        accepted = validate_success(
            api.accept_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], ANALYST_1), 200
        )
        assert accepted["status"] == "ACCEPTED"
        assert accepted["approved_by"] == "analyst-1"
        for exception in ctx["exceptions"]:
            assert _exception(api, exception["id"])["status"] == "IN_REMEDIATION"
        assert _open_count(api, ctx["cycle"]["id"]) == 2, "Accept conserves the open count"

    def test_accept_then_verify_reject_restores_original_state(self, api):
        """PRD §3.6: "Acceptance records the analyst's `X-User-ID` in the plan's
        `approved_by` and moves every linked exception `OPEN → IN_REMEDIATION` — the
        exceptions are still open, so `open_exception_count` does not change."
        PRD §3.6: "A failed verification — invoked with `reject` set true — moves
        the plan to `REJECTED` and compensates by returning every linked exception
        to `OPEN`, leaving `open_exception_count` unchanged; plan and cycle versions
        increment accordingly."

        The forward accept plus compensating reject leaves the count at exactly the
        pre-accept value.

        Design: Difficulty/compensating_invariant/open_exception_count_conserved_across_plan_lifecycle
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM", "LOW"))
        assert _open_count(api, ctx["cycle"]["id"]) == 2
        plan, _acceptor = setup_completed_plan(ctx)
        rejected = validate_success(
            api.verify_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], {"reject": True}, ANALYST_2),
            200,
        )
        assert rejected["status"] == "REJECTED"
        for exception in ctx["exceptions"]:
            assert _exception(api, exception["id"])["status"] == "OPEN"
        assert _open_count(api, ctx["cycle"]["id"]) == 2


class TestStateBeforeSegregation:
    def test_verify_proposed_plan_rejected_invalid_state(self, api):
        """PRD §3.6: "Verification returns to a `RiskAnalyst` and acts only on a
        `COMPLETED` plan; per §2.8 the verifier must differ from the analyst
        recorded in `approved_by`."
        PRD §2.9: "State permission — the target resource must be in a state that
        permits the requested transition; failures yield `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/state_before_segregation_of_duties_on_verify
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        plan = setup_proposed_plan(ctx)
        res = api.verify_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], {}, ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert _plan(api, ctx, plan["id"])["status"] == "PROPOSED"

    def test_state_check_fires_before_segregation_check(self, api):
        """PRD §2.9: "Every request is evaluated against one ordered validation
        cascade, and the first failing check determines the error returned — a
        request that fails an early check never surfaces a later one:"
        PRD §2.9: "4. State permission — the target resource must be in a state that
        permits the requested transition; failures yield `ERR_INVALID_STATE` (409)."
        PRD §2.9: "5. Segregation of duties — per §2.8; failures yield
        `ERR_SEGREGATION_OF_DUTIES` (422)."

        The plan is ACCEPTED (not COMPLETED) and the verifier is the accepting
        analyst, so both checks could fire; the state check must win.

        Design: Difficulty/priority_pair_validation_conflict/state_before_segregation_of_duties_on_verify
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        plan = setup_proposed_plan(ctx)
        accepted = validate_success(
            api.accept_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], ANALYST_1), 200
        )
        assert accepted["status"] == "ACCEPTED"
        res = api.verify_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], {}, ANALYST_1)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert _plan(api, ctx, plan["id"])["status"] == "ACCEPTED"


class TestSegregationOfDuties:
    def test_plan_verifier_must_differ_from_acceptor(self, api):
        """PRD §2.8: "the verifier of a remediation plan must differ from the analyst
        who accepted it (recorded as the plan's `approved_by`); the approver of a
        subprocessor disclosure must differ from the analyst who started its review;
        and the approver of an assessment cycle must differ from the analyst who
        completed the cycle's evidence review. Any attempt by one person to perform
        both halves of a gated pair is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 422)."

        Design: Corner/validations/segregation_of_duties_plan_verifier_not_approver
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        plan, _acceptor = setup_completed_plan(ctx)  # accepted by analyst-1
        res = api.verify_plan(ctx["vendor"]["id"], ctx["cycle"]["id"], plan["id"], {}, ANALYST_1)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert _plan(api, ctx, plan["id"])["status"] == "COMPLETED"


class TestCycleTerminalLockdown:
    def test_score_on_rejected_cycle_rejected(self, api):
        """PRD §3.7: "Rejecting the cycle instead moves it to `REJECTED`, drops the
        vendor's posture to `SUSPENDED`, clears `active_cycle_id`, and increments
        the vendor's `version`."
        PRD §2.9: "State permission — the target resource must be in a state that
        permits the requested transition; failures yield `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/cycle_terminal_state_lockdown
        """
        ctx = setup_risk_acceptance_review_cycle()
        rejected = validate_success(
            api.reject_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], APPROVER), 200
        )
        assert rejected["status"] == "REJECTED"
        res = api.score_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "REJECTED"
