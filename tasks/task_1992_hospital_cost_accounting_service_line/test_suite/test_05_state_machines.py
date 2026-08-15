"""State-machine cycles, forks, invalid transitions, terminal states (PRD §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_cost_model,
    create_case,
    create_overhead_center,
    create_service_line,
    get_success_data,
    post_case,
    propose_refresh,
    setup_case_with_lines,
    setup_card_rvu,
    setup_ortho_tdabc,
    validate_error,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestPhysicianCycle:
    def test_physician_deactivate_reactivate_cycle(self, api):
        """PRD §3.1: "A physician may be deactivated — `ACTIVE` to `INACTIVE` —
        only while no `DRAFT` or `POSTED` case references them, else
        `ERR_PHYSICIAN_HAS_OPEN_CASES`; reactivation returns an `INACTIVE`
        physician to `ACTIVE` without preconditions."

        Design: Difficulty/non_linear_state_machine/physician_deactivate_reactivate_cycle
        """
        from test_helpers import create_physician
        phys = create_physician(npi="1000000003", full_name="Dr. Three", specialty="ENT")
        assert phys["status"] == "ACTIVE"

        deactivated = validate_success(api.deactivate_physician(phys["id"], FC))
        assert deactivated["status"] == "INACTIVE"

        reactivated = validate_success(api.reactivate_physician(phys["id"], FC))
        assert reactivated["status"] == "ACTIVE"

        # The loop can repeat: a second deactivate after reactivation succeeds.
        deactivated_again = validate_success(api.deactivate_physician(phys["id"], FC))
        assert deactivated_again["status"] == "INACTIVE"

    def test_physician_reactivate_restores_case_creation_eligibility(self, api):
        """PRD §3.1: "reactivation returns an `INACTIVE` physician to `ACTIVE`
        without preconditions."
        PRD §3.3: "the physician must be `ACTIVE` (else `ERR_PHYSICIAN_NOT_ACTIVE`)"

        Design: Difficulty/non_linear_state_machine/physician_deactivate_reactivate_cycle
        """
        from test_helpers import create_physician
        scenario = setup_ortho_tdabc()
        phys = create_physician(npi="1000000003", full_name="Dr. Three", specialty="ENT")
        validate_success(api.deactivate_physician(phys["id"], FC))
        validate_success(api.reactivate_physician(phys["id"], FC))

        # After the deactivate->reactivate loop the physician is ACTIVE again and
        # case creation (which demands an ACTIVE physician) is admitted.
        case = create_case(
            service_line_id=scenario["service_line"]["id"],
            physician_id=phys["id"],
            drg_id=scenario["drg"]["id"],
            cost_model_id=scenario["model"]["id"],
            period="2026-08",
            expected_reimbursement=30000.00,
        )
        assert case["status"] == "DRAFT"
        assert case["physician_id"] == phys["id"]


class TestRefreshFork:
    def test_refresh_approve_reject_branching_fork(self, api):
        """PRD §3.6: "Approval is a `FinanceController` decision and moves the
        refresh `PROPOSED → APPROVED` behind three governance gates"
        PRD §3.6: "A `PROPOSED` refresh may instead be rejected outright, moving
        it to `REJECTED` with no further preconditions."

        Design: Difficulty/non_linear_state_machine/refresh_approve_reject_branching_fork
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        from test_helpers import create_rvu_center
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        model, model_v = create_active_cost_model(
            name="ORTHO-RVU", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")

        rates = [{"cost_center_id": cc_lab["id"], "allocated_cost": 5100.00, "total_rvu": 2.0}]
        r1 = propose_refresh(model["id"], "2026-09", rates, data_quality_score=90.0)
        r2 = propose_refresh(model["id"], "2026-09", rates, data_quality_score=90.0)

        approved = validate_success(
            api.approve_cost_model_refresh(r1["id"], {"expected_model_version": model_v}, FC)
        )
        assert approved["status"] == "APPROVED"

        rejected = validate_success(api.reject_cost_model_refresh(r2["id"], FC))
        assert rejected["status"] == "REJECTED"

        apply_rejected = api.apply_cost_model_refresh(r2["id"], FC)
        validate_error(apply_rejected, ApiErrorId.ERR_INVALID_STATE)

    def test_refresh_approved_branch_admits_apply(self, api):
        """PRD §3.6: "Application, again by a `FinanceController`, moves an
        `APPROVED` refresh to `APPLIED` and is the most consequential action in
        the system."

        Design: Difficulty/non_linear_state_machine/refresh_approve_reject_branching_fork
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        from test_helpers import create_rvu_center
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop Services", code="PERIOP",
                                           allocated_cost=7000.00)
        model, model_v = create_active_cost_model(
            name="ORTHO-RVU", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        rates = [{"cost_center_id": cc_lab["id"], "allocated_cost": 5100.00, "total_rvu": 2.0}]
        refresh = propose_refresh(model["id"], "2026-09", rates, data_quality_score=90.0)
        validate_success(
            api.approve_cost_model_refresh(refresh["id"], {"expected_model_version": model_v}, FC)
        )

        applied = validate_success(api.apply_cost_model_refresh(refresh["id"], FC))
        assert applied["status"] == "APPLIED"


class TestCostModelTransitions:
    def test_cost_model_approve_from_active_rejected(self, api):
        """PRD §2.10: "the addressed resource must be in the state the transition
        requires (posting requires a `DRAFT` case, refresh approval requires a
        `PROPOSED` refresh, case locking requires a `POSTED` case, and so on),
        else `ERR_INVALID_STATE`."
        PRD §3.2: "Approval is the `FinanceController`'s gate and moves the model
        `DRAFT → ACTIVE`."

        Design: Corner/state_machines/cost_model_approve_from_active_rejected
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        _model, _v = create_active_cost_model(
            name="M", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")

        second = api.approve_cost_model(_model["id"], FC)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_cost_model_terminal_superseded_no_further_transition(self, api):
        """PRD §3.2: "Upon approval the named supersession target transitions to
        `SUPERSEDED`, and the newly approved model's `version` increments by one."
        PRD §2.10: "the addressed resource must be in the state the transition
        requires (posting requires a `DRAFT` case, refresh approval requires a
        `PROPOSED` refresh, case locking requires a `POSTED` case, and so on),
        else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cost_model_terminal_superseded_no_further_transition
        """
        from test_helpers import create_draft_cost_model
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        m1, _m1_v = create_active_cost_model(
            name="M1", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        m2 = create_draft_cost_model(
            name="M2", service_line_id=sl["id"], allocation_basis="TDABC",
            rate_factor=1.10, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-02", supersedes_model_id=m1["id"])
        validate_success(api.approve_cost_model(m2["id"], FC))

        superseded = validate_success(api.get_cost_model(m1["id"], FC))
        assert superseded["status"] == "SUPERSEDED"

        # SUPERSEDED is terminal: archiving it fails.
        archived = api.archive_cost_model(m1["id"], FC)
        validate_error(archived, ApiErrorId.ERR_INVALID_STATE)

        # Still retrievable with status SUPERSEDED.
        still = validate_success(api.get_cost_model(m1["id"], FC))
        assert still["status"] == "SUPERSEDED"


class TestCaseTransitions:
    def test_case_void_from_draft_rejected(self, api):
        """PRD §3.4: "Voiding moves a `POSTED` case to `VOIDED` with no further
        preconditions."
        PRD §2.10: "the addressed resource must be in the state the transition
        requires (posting requires a `DRAFT` case, refresh approval requires a
        `PROPOSED` refresh, case locking requires a `POSTED` case, and so on),
        else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/case_void_from_draft_rejected
        """
        scenario = setup_ortho_tdabc()
        case = create_case(
            service_line_id=scenario["service_line"]["id"],
            physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"],
            cost_model_id=scenario["model"]["id"],
            period="2026-08",
            expected_reimbursement=30000.00,
        )
        resp = api.void_case(case["id"], CA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_case_post_without_activity_lines_rejected(self, api):
        """PRD §3.4: "Three further preconditions guard the transition: at least
        one activity cost line must exist for the case (else
        `ERR_CASE_NO_ACTIVITY`); the case's `period` must not precede the model's
        `effective_period` (else `ERR_CASE_PERIOD_BEFORE_MODEL`); and the model
        must be `ACTIVE` (else `ERR_MODEL_NOT_ACTIVE`)."

        Design: Corner/state_machines/case_post_without_activity_lines_rejected
        """
        scenario = setup_ortho_tdabc()
        case = create_case(
            service_line_id=scenario["service_line"]["id"],
            physician_id=scenario["physician"]["id"],
            drg_id=scenario["drg"]["id"],
            cost_model_id=scenario["model"]["id"],
            period="2026-08",
            expected_reimbursement=30000.00,
        )
        resp = api.post_case(case["id"], {"expected_model_version": scenario["model_version"]}, CA)
        validate_error(resp, ApiErrorId.ERR_CASE_NO_ACTIVITY)


class TestRefreshTerminalStates:
    def test_refresh_rejected_is_terminal_apply_fails(self, api):
        """PRD §3.6: "A `PROPOSED` refresh may instead be rejected outright, moving
        it to `REJECTED` with no further preconditions."
        PRD §3.6: "Application, again by a `FinanceController`, moves an
        `APPROVED` refresh to `APPLIED`"
        PRD §2.10: "the addressed resource must be in the state the transition
        requires (posting requires a `DRAFT` case, refresh approval requires a
        `PROPOSED` refresh, case locking requires a `POSTED` case, and so on),
        else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/refresh_rejected_is_terminal_apply_fails
        """
        sl = create_service_line(name="Orthopedic Surgery", code="ORTHO",
                                 base_direct_cost=9000.00, budgeted_volume=120)
        from test_helpers import create_rvu_center
        cc_lab = create_rvu_center(name="Laboratory", code="LAB",
                                   allocated_cost=5000.00, total_rvu=2.0)
        cc_periop = create_overhead_center(name="Periop", code="PERIOP",
                                           allocated_cost=7000.00)
        model, _v = create_active_cost_model(
            name="M", service_line_id=sl["id"], allocation_basis="RVU",
            rate_factor=1.00, overhead_cost_center_id=cc_periop["id"],
            effective_period="2026-01")
        refresh = propose_refresh(
            model["id"], "2026-09",
            [{"cost_center_id": cc_lab["id"], "allocated_cost": 5100.00, "total_rvu": 2.0}],
            data_quality_score=95.0,
        )
        validate_success(api.reject_cost_model_refresh(refresh["id"], FC))

        resp = api.apply_cost_model_refresh(refresh["id"], FC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
