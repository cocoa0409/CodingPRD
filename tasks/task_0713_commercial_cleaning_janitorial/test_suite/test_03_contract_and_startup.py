"""Contract signing, start-up crewing, go-live cascade, abort cascade, hour conservation."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_contract_payload, create_crew_shift_payload,
    setup_signed_contract, setup_crewed_plan, setup_servicing_contract,
    setup_sent_proposal, create_available_crew,
    STANDARD_AREAS, SINGLE_LIGHT_AREA, TEST_USERS,
)
from test_helpers import api_client

_SALES = TEST_USERS["sales_rep_headers"]
_OPS = TEST_USERS["operations_manager_headers"]


class TestSignRequiresAcceptedProposal:
    """Difficulty rule: cross_entity_state_dependency / sign_requires_proposal_accepted."""

    def test_sign_with_non_accepted_proposal_rejected(self, api):
        """PRD §3.6: "the linked proposal named by proposal_id must be in status
        ACCEPTED, otherwise the sign is rejected with ERR_PROPOSAL_NOT_ACCEPTED."

        Design: Difficulty/cross_entity_state_dependency/sign_requires_proposal_accepted
        """
        # A SENT (not ACCEPTED) proposal. If the implementation lets a contract be
        # drafted from it, signing must reject; if it rejects at create, the proposal-
        # not-accepted error surfaces there. Either way the rule is the ACCEPTED gate.
        acct, rfp, bid, prop = setup_sent_proposal(areas=SINGLE_LIGHT_AREA, legal_name="Xdep Co")
        create_res = api.create_contract(acct["id"], create_contract_payload(prop["id"]), _SALES)
        if create_res.status_code == 201:
            ctr = create_res.json()["data"]
            validate_error(api.sign_contract(acct["id"], ctr["id"], _SALES),
                           "ERR_PROPOSAL_NOT_ACCEPTED")
        else:
            validate_error(create_res, "ERR_PROPOSAL_NOT_ACCEPTED")

    def test_sign_succeeds_when_proposal_accepted(self, api):
        """PRD §3.6: "Signing the contract advances its lifecycle_status from DRAFT to
        SIGNED."
        PRD §3.6: "the linked proposal named by proposal_id must be in status ACCEPTED,
        otherwise the sign is rejected with ERR_PROPOSAL_NOT_ACCEPTED."

        Design: Difficulty/cross_entity_state_dependency/sign_requires_proposal_accepted
        """
        acct, rfp, bid, prop, ctr, plan = setup_signed_contract(
            areas=SINGLE_LIGHT_AREA, legal_name="Xdep OK Co")
        assert ctr["lifecycle_status"] == "SIGNED"


class TestCrewAssignmentStateDependency:
    """Difficulty rule: cross_entity_state_dependency / crew_assignment_requires_contract_signed."""

    def test_crew_on_aborted_plan_rejected(self, api):
        """PRD §3.7: "the plan must be in PLANNING for the first shift (or CREWED for an
        additional shift), otherwise ERR_INVALID_STATE".
        PRD §3.8: "Aborting is permitted while the plan is PLANNING, CREWED, or READY,
        otherwise ERR_INVALID_STATE; it moves the plan to ABORTED."

        Design: Difficulty/cross_entity_state_dependency/crew_assignment_requires_contract_signed
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Crew Dep Co")
        validate_success(api.abort_plan(acct["id"], plan["id"], _OPS), 200)
        res = api.assign_crew_shift(
            acct["id"], plan["id"],
            create_crew_shift_payload(crew["id"], start_at="2026-03-04T09:00:00Z",
                                      end_at="2026-03-04T14:00:00Z"), _OPS)
        validate_error(res, "ERR_INVALID_STATE")

    def test_aborted_plan_stays_aborted_after_crew_attempt(self, api):
        """PRD §3.8: "Aborting is permitted while the plan is PLANNING, CREWED, or
        READY, otherwise ERR_INVALID_STATE; it moves the plan to ABORTED."
        PRD §3.7: "the plan must be in PLANNING for the first shift (or CREWED for an
        additional shift), otherwise ERR_INVALID_STATE".

        Design: Difficulty/cross_entity_state_dependency/crew_assignment_requires_contract_signed
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Crew Dep Co 2")
        validate_success(api.abort_plan(acct["id"], plan["id"], _OPS), 200)
        api.assign_crew_shift(
            acct["id"], plan["id"],
            create_crew_shift_payload(crew["id"], start_at="2026-03-05T09:00:00Z",
                                      end_at="2026-03-05T14:00:00Z"), _OPS)
        plan_after = validate_success(api.get_startup_plan(acct["id"], plan["id"], _OPS), 200)
        assert plan_after["status"] == "ABORTED"


class TestContractParallelAxes:
    """Difficulty rule: non_linear_state_machine / contract_parallel_lifecycle_and_billing_axes."""

    def test_suspend_then_resume_billing_axis_independent(self, api):
        """PRD §2.8: "The two axes evolve independently: suspending or resuming billing
        never changes lifecycle_status, and most lifecycle transitions leave
        billing_status untouched."
        PRD §3.10: "Resuming billing moves billing_status from SUSPENDED back to ACTIVE".

        Design: Difficulty/non_linear_state_machine/contract_parallel_lifecycle_and_billing_axes
        """
        from test_helpers import make_account_manager_headers
        from test_helpers.fixtures import AM_USER_ID
        am = make_account_manager_headers(AM_USER_ID)
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="Parallel Co")
        validate_success(api.suspend_billing(acct["id"], ctr["id"], am), 200)
        resumed = validate_success(api.resume_billing(acct["id"], ctr["id"], am), 200)
        assert resumed["billing_status"] == "ACTIVE"
        assert resumed["lifecycle_status"] == "SERVICING"

    def test_suspend_leaves_lifecycle_servicing(self, api):
        """PRD §3.10: "Suspension debits the account's health_score by the suspend
        penalty, floored at 0, and leaves lifecycle_status unchanged."

        Design: Difficulty/non_linear_state_machine/contract_parallel_lifecycle_and_billing_axes
        """
        from test_helpers import make_account_manager_headers
        from test_helpers.fixtures import AM_USER_ID
        am = make_account_manager_headers(AM_USER_ID)
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="Parallel Co 2")
        suspended = validate_success(api.suspend_billing(acct["id"], ctr["id"], am), 200)
        assert suspended["billing_status"] == "SUSPENDED"
        assert suspended["lifecycle_status"] == "SERVICING"


class TestGoLiveCascade:
    """Difficulty rule: transitive_cascade / golive_cascade_plan_contract_account_billing_depth4."""

    def test_go_live_cascades_plan_contract_billing(self, api):
        """PRD §3.8: "Going live advances the parent contract's lifecycle_status from
        STARTUP to SERVICING, moves the contract's billing_status from PENDING to ACTIVE
        as the cross-axis activation, and promotes the account's lifecycle_stage from
        PROSPECT to ACTIVE_CUSTOMER, completing the handoff to account management."

        Design: Difficulty/transitive_cascade/golive_cascade_plan_contract_account_billing_depth4
        """
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="Cascade Co")
        assert plan["status"] == "LIVE"
        assert ctr["lifecycle_status"] == "SERVICING"
        assert ctr["billing_status"] == "ACTIVE"

    def test_go_live_promotes_account_to_active_customer(self, api):
        """PRD §3.8: "promotes the account's lifecycle_stage from PROSPECT to
        ACTIVE_CUSTOMER, completing the handoff to account management."

        Design: Difficulty/transitive_cascade/golive_cascade_plan_contract_account_billing_depth4
        """
        acct, rfp, ctr, plan = setup_servicing_contract(areas=SINGLE_LIGHT_AREA, legal_name="Cascade Co 2")
        acct_after = validate_success(api.get_account(acct["id"], _SALES), 200)
        assert acct_after["lifecycle_stage"] == "ACTIVE_CUSTOMER"


class TestAbortCascade:
    """Difficulty rule: transitive_cascade / abort_cascade_shifts_hours_health_depth3."""

    def test_abort_cancels_shift_and_releases_hours(self, api):
        """PRD §3.8: "Abort cancels every ASSIGNED crew shift on the plan, setting each
        to CANCELLED and releasing its shift_hours back so the allocation drops
        accordingly".
        PRD §3.7: "The plan's allocated_hours is the sum of shift_hours over every crew
        shift on the plan whose status is ASSIGNED".

        Design: Difficulty/transitive_cascade/abort_cascade_shifts_hours_health_depth3
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Abort Co")
        aborted = validate_success(api.abort_plan(acct["id"], plan["id"], _OPS), 200)
        assert aborted["status"] == "ABORTED"
        assert aborted["allocated_hours"] == 0.00

    def test_abort_cancels_the_assigned_shift(self, api):
        """PRD §3.8: "Abort cancels every ASSIGNED crew shift on the plan, setting each
        to CANCELLED and releasing its shift_hours back so the allocation drops
        accordingly".

        Design: Difficulty/transitive_cascade/abort_cascade_shifts_hours_health_depth3
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Abort Co 2")
        validate_success(api.abort_plan(acct["id"], plan["id"], _OPS), 200)
        shifts, _meta = validate_paginated(api.list_plan_crew_shifts(acct["id"], plan["id"], _OPS))
        statuses = [s["status"] for s in shifts]
        assert "CANCELLED" in statuses, f"expected a CANCELLED shift, got {statuses}"


class TestHourConservation:
    """Difficulty rule: compensating_invariant / labor_hours_conservation_shift_assign_then_cancel."""

    def test_cancel_shift_releases_allocated_hours(self, api):
        """PRD §3.7: "Cancelling an ASSIGNED shift moves it to CANCELLED and, as a
        compensating release, subtracts that shift's shift_hours from the plan's
        allocated_hours, preserving the allocation invariant."

        Design: Difficulty/compensating_invariant/labor_hours_conservation_shift_assign_then_cancel
        """
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Hrs Co")
        cancelled = validate_success(api.cancel_crew_shift(acct["id"], shift["id"], _OPS), 200)
        assert cancelled["status"] == "CANCELLED"
        plan_after = validate_success(api.get_startup_plan(acct["id"], plan["id"], _OPS), 200)
        assert plan_after["allocated_hours"] == 0.00

    def test_allocated_hours_reflects_assigned_shift(self, api):
        """PRD §3.7: "The plan's allocated_hours is the sum of shift_hours over every
        crew shift on the plan whose status is ASSIGNED, rounded half up to two decimal
        places".
        PRD §3.7: "a read-only shift_hours equal to the elapsed time from start_at to
        end_at expressed in hours to two decimal places."

        Design: Difficulty/compensating_invariant/labor_hours_conservation_shift_assign_then_cancel
        """
        # A 09:00-14:00 shift is 5.00 hours; allocated_hours equals that single shift.
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=SINGLE_LIGHT_AREA, legal_name="Hrs Co 2")
        assert shift["shift_hours"] == 5.00
        plan_now = validate_success(api.get_startup_plan(acct["id"], plan["id"], _OPS), 200)
        assert plan_now["allocated_hours"] == 5.00


class TestStartupCornerClaims:
    """Corner section: state_machines (precondition enforcement)."""

    def test_mark_ready_underallocated_rejected(self, api):
        """PRD §3.8: "The plan must be CREWED (ERR_INVALID_STATE) and its
        allocated_hours must be at least its planned_monthly_hours; if hours are still
        short, mark-ready is rejected with ERR_HOURS_UNDERALLOCATED."

        Design: Corner/state_machines/mark_ready_underallocated_returns_hours_underallocated
        """
        # STANDARD areas give planned_monthly_hours = 187.62, but a single 4h shift is
        # far short, so mark-ready is rejected.
        acct, rfp, ctr, plan, crew, shift = setup_crewed_plan(
            areas=STANDARD_AREAS, legal_name="Under Co", crew_capacity=200,
            shift_start="2026-03-03T09:00:00Z", shift_end="2026-03-03T13:00:00Z")
        res = api.mark_ready(acct["id"], plan["id"], _OPS)
        validate_error(res, "ERR_HOURS_UNDERALLOCATED")
        plan_after = validate_success(api.get_startup_plan(acct["id"], plan["id"], _OPS), 200)
        assert plan_after["status"] == "CREWED"

    def test_crew_assignment_on_retired_crew_rejected(self, api):
        """PRD §3.7: "the named crew must be AVAILABLE, otherwise ERR_CREW_UNAVAILABLE".
        PRD §3.7: "Retiring a crew sets its status to RETIRED."

        Design: Corner/state_machines/crew_assignment_on_retired_crew_returns_crew_unavailable
        """
        acct, rfp, bid, prop, ctr, plan = setup_signed_contract(
            areas=SINGLE_LIGHT_AREA, legal_name="Retire Co")
        crew = create_available_crew(name="Cret")
        validate_success(api.retire_crew(crew["id"], _OPS), 200)
        res = api.assign_crew_shift(
            acct["id"], plan["id"], create_crew_shift_payload(crew["id"]), _OPS)
        validate_error(res, "ERR_CREW_UNAVAILABLE")
