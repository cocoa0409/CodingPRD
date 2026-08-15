"""Deal pipeline state machine, invalid transitions, terminal lockdowns (PRD §3.5, §3.7, §3.1)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_deal_payload,
    setup_active_agent, setup_agent_on_plan, setup_agent_with_debit,
    create_draft_deal, setup_pending_deal,
    setup_closed_deal, setup_settled_deal, get_leg_by_type,
    authorize_leg, release_leg, make_office_manager_headers,
    make_transaction_coordinator_headers,
)


class TestDealInvalidTransitionBattery:
    def test_actions_from_draft_are_rejected(self, api):
        """PRD §3.5: "Operating on a deal from a state that does not permit the
        action is rejected with ERR_DEAL_INVALID_STATE (HTTP 409)."

        Design: Corner/state_machines/deal_invalid_transition_battery
        """
        agent = setup_active_agent(name="Battery Bill")
        deal = create_draft_deal(agent["id"], address="6 Battery Way",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        for resp in (
            api.close_deal(deal["id"], {}, TEST_USERS["transaction_coordinator_headers"]),
            api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
            api.withdraw_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
            api.fall_through_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
            api.void_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
        ):
            validate_error(resp, ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)

    def test_settle_and_void_from_pending_rejected_then_settled_battery(self, api):
        """PRD §3.5: "Operating on a deal from a state that does not permit the
        action is rejected with ERR_DEAL_INVALID_STATE (HTTP 409)."
        PRD §3.6: "a SETTLED deal specifically is rejected with
        ERR_DEAL_HAS_SETTLEMENT, HTTP 409, since at most one non-REVERSED
        settlement may exist per deal".

        Design: Corner/state_machines/deal_invalid_transition_battery
        """
        agent, plan, _enr = setup_agent_on_plan(agent_name="Battery Bill")
        deal = create_draft_deal(agent["id"], address="6 Battery Way",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        deal = get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        # From PENDING_CLOSING
        validate_error(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)
        validate_error(api.void_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)
        # Drive to SETTLED
        get_success_data(api.close_deal(deal["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        settlement = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert settlement["status"] == "POSTED"
        # Settle again -> domain-specific ERR_DEAL_HAS_SETTLEMENT
        validate_error(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_HAS_SETTLEMENT, expected_status=409)
        # Other actions from SETTLED -> generic state error
        validate_error(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)
        validate_error(api.fall_through_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)


class TestLegInvalidTransitionBattery:
    def test_release_before_authorize_and_terminal_lockdown(self, api):
        """PRD §3.7: "Voiding from any other state is `ERR_LEG_INVALID_STATE`,
        and `RELEASED` is terminal — released money is gone". Also: "the leg
        must be `SCHEDULED`, else `ERR_LEG_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/leg_invalid_transition_battery
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Leg Larry")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        leg = get_leg_by_type(settlement["id"], "AGENT")

        # release from SCHEDULED rejected
        validate_error(
            api.release_leg(leg["id"], make_office_manager_headers("om-2")),
            ApiErrorId.ERR_LEG_INVALID_STATE, expected_status=409)
        # authorize ok
        authorize_leg(leg["id"], user_id="om-1")
        # double authorize rejected
        validate_error(
            api.authorize_leg(leg["id"], make_office_manager_headers("om-2")),
            ApiErrorId.ERR_LEG_INVALID_STATE, expected_status=409)
        # release ok
        released = release_leg(leg["id"], user_id="om-2")
        assert released["status"] == "RELEASED"
        # terminal lockdown
        validate_error(
            api.void_leg(leg["id"], make_office_manager_headers("om-1")),
            ApiErrorId.ERR_LEG_INVALID_STATE, expected_status=409)
        validate_error(
            api.authorize_leg(leg["id"], make_office_manager_headers("om-1")),
            ApiErrorId.ERR_LEG_INVALID_STATE, expected_status=409)

    def test_release_requires_authorized_state(self, api):
        """PRD §3.7: "an `OfficeManager` or `BrokerAdmin` moves an `AUTHORIZED`
        leg to `RELEASED` under the same state guards" — a leg still `SCHEDULED`
        cannot be released.

        Design: Corner/state_machines/leg_invalid_transition_battery
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Leg Larry")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        leg = get_leg_by_type(settlement["id"], "AGENT")
        validate_error(
            api.release_leg(leg["id"], make_office_manager_headers("om-9")),
            ApiErrorId.ERR_LEG_INVALID_STATE, expected_status=409)


class TestTerminalStateLockdowns:
    def test_terminal_states_reject_further_transitions(self, api):
        """PRD §3.5: "FELL_THROUGH, VOIDED, and ultimately DISBURSED (§3.7) are the
        deal's terminal states." PRD §3.9: "Finalizing or voiding from a state that
        does not permit it is rejected with ERR_TAX_FORM_INVALID_STATE (HTTP 409)".
        PRD §3.1: "Termination is the terminal act of the lifecycle" — an
        already-TERMINATED agent cannot be activated or re-terminated
        (ERR_AGENT_INVALID_STATE).

        Design: Corner/state_machines/terminal_state_lockdowns
        """
        agent = setup_active_agent(name="Term Tina")
        # Deal A -> FELL_THROUGH
        da = create_draft_deal(agent["id"], address="8 Dead Deal Dr",
                               gross_commission_cents=100000, closing_date="2026-01-15")
        get_success_data(api.submit_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.fall_through_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]))
        # Deal B -> VOIDED
        db = create_draft_deal(agent["id"], address="9 Voided Way",
                               gross_commission_cents=100000, closing_date="2026-01-16")
        get_success_data(api.submit_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.close_deal(db["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.void_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]))
        # Tax form -> VOIDED
        tf = get_success_data(api.create_tax_form(agent["id"], {"tax_year": 2026},
                                                  TEST_USERS["broker_admin_headers"]))
        get_success_data(api.void_tax_form(tf["id"], TEST_USERS["broker_admin_headers"]))
        # Terminated agent
        other = get_success_data(api.create_agent(
            create_agent_payload(full_name="Gone Gary", email="gg@x.com",
                                 license_number="LIC-TE2", joined_at="2025-09-01"),
            TEST_USERS["broker_admin_headers"]))
        get_success_data(api.terminate_agent(other["id"], TEST_USERS["broker_admin_headers"]))

        validate_error(api.submit_deal(da["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)
        validate_error(api.settle_deal(db["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)
        validate_error(api.finalize_tax_form(tf["id"], TEST_USERS["broker_admin_headers"]),
                       ApiErrorId.ERR_TAX_FORM_INVALID_STATE, expected_status=409)
        validate_error(api.activate_agent(other["id"], TEST_USERS["broker_admin_headers"]),
                       ApiErrorId.ERR_AGENT_INVALID_STATE, expected_status=409)
        validate_error(api.terminate_agent(other["id"], TEST_USERS["broker_admin_headers"]),
                       ApiErrorId.ERR_AGENT_INVALID_STATE, expected_status=409)

    def test_voided_deal_cannot_be_settled(self, api):
        """PRD §3.5: "Operating on a deal from a state that does not permit the
        action is rejected with ERR_DEAL_INVALID_STATE (HTTP 409)"; VOIDED is a
        terminal state.

        Design: Corner/state_machines/terminal_state_lockdowns
        """
        agent = setup_active_agent(name="Term Tina")
        deal = create_draft_deal(agent["id"], address="9 Voided Way",
                                 gross_commission_cents=100000, closing_date="2026-01-16")
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.close_deal(deal["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.void_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        validate_error(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]),
                       ApiErrorId.ERR_DEAL_INVALID_STATE, expected_status=409)


class TestAgentSuspendReinstateCycle:
    def test_suspend_reinstate_twice_preserves_financials(self, api):
        """PRD §3.1: "Suspension moves an agent from ACTIVE to SUSPENDED — a
        suspended agent keeps their existing deal pipeline but cannot create new
        deals — and reinstatement returns them from SUSPENDED to ACTIVE."

        Design: Difficulty/non_linear_state_machine/agent_suspend_reinstate_cycle_preserves_financial_state
        """
        agent, plan, _e = setup_agent_with_debit(150000, agent_name="Susie Pend")
        settlement, deal = setup_settled_deal(agent["id"], poster_user_id="tc-1")
        # Loop 1
        st1 = get_success_data(api.suspend_agent(agent["id"], TEST_USERS["broker_admin_headers"]))["status"]
        st2 = get_success_data(api.reinstate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))["status"]
        # Loop 2 (only suspend this time in the recipe)
        st3 = get_success_data(api.suspend_agent(agent["id"], TEST_USERS["broker_admin_headers"]))["status"]
        assert (st1, st2, st3) == ("SUSPENDED", "ACTIVE", "SUSPENDED")
        final = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert final["debit_balance_cents"] == 0
        assert final["settled_deal_count"] == 1

    def test_suspend_reinstate_leaves_enrollment_active(self, api):
        """PRD §3.1: "a suspended agent keeps their existing deal pipeline" —
        suspension never cascades to the agent's enrollment; the enrollment
        stays ACTIVE across a suspend/reinstate cycle.

        Design: Difficulty/non_linear_state_machine/agent_suspend_reinstate_cycle_preserves_financial_state
        """
        agent, plan, enrollment = setup_agent_with_debit(150000, agent_name="Susie Pend")
        setup_settled_deal(agent["id"], poster_user_id="tc-1")
        get_success_data(api.suspend_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        get_success_data(api.reinstate_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        enr = get_success_data(api.get_enrollment(enrollment["id"], TEST_USERS["broker_admin_headers"]))
        assert enr["status"] == "ACTIVE"


class TestDealEditCycleAndSettleUnsettleLoop:
    def test_edit_cycle_then_settle_unsettle_settle_again(self, api):
        """PRD §3.5: "Submitting moves the deal from DRAFT to PENDING_CLOSING;
        withdrawing cycles it back from PENDING_CLOSING to DRAFT for further
        editing." PRD §3.8: "Unsettling is the full-reversal act ... the deal
        returns to CLOSED". PRD §3.8: "the anniversary window's accumulators are
        restored exactly — ... so cap room returns precisely".

        Design: Difficulty/non_linear_state_machine/deal_edit_cycle_and_settle_unsettle_loop
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Cycla Cycle")
        deal = create_draft_deal(agent["id"], address="20 Loop Ln",
                                 gross_commission_cents=900000, closing_date="2026-01-15")
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        back = get_success_data(api.withdraw_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert back["status"] == "DRAFT"
        get_success_data(api.put_deal(deal["id"], {
            "address": "20 Loop Ln", "gross_commission_cents": 1000000,
            "closing_date": "2026-01-15",
        }, TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        get_success_data(api.close_deal(deal["id"], {}, TEST_USERS["transaction_coordinator_headers"]))
        first = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert first["company_dollar_cents"] == 282000
        back2 = get_success_data(api.unsettle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert back2["status"] == "CLOSED"
        second = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert second["company_dollar_cents"] == 282000
        assert second["status"] == "POSTED"

    def test_withdraw_returns_to_draft_for_editing(self, api):
        """PRD §3.5: "withdrawing cycles it back from PENDING_CLOSING to DRAFT for
        further editing; both actions are open to the owning agent or a
        coordinator".

        Design: Difficulty/non_linear_state_machine/deal_edit_cycle_and_settle_unsettle_loop
        """
        agent = setup_active_agent(name="Cycla Cycle")
        deal = create_draft_deal(agent["id"], gross_commission_cents=900000)
        get_success_data(api.submit_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        back = get_success_data(api.withdraw_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert back["status"] == "DRAFT"
        # Editable again in DRAFT
        edited = get_success_data(api.put_deal(deal["id"], {
            "address": "20 Loop Ln", "gross_commission_cents": 1000000,
            "closing_date": "2026-01-15",
        }, TEST_USERS["transaction_coordinator_headers"]))
        assert edited["gross_commission_cents"] == 1000000
