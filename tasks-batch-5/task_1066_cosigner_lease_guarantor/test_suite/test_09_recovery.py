"""Recovering disbursed funds: installment posting/reversal conservation and
auto-settlement (PRD §3.7)."""
from test_helpers import (
    validate_success, get_success_data,
    setup_paid_claim, assert_recovery_principal_conserved,
    make_recovery_agent_headers, TEST_USERS,
)


class TestRecoveryPrincipalConservation:
    """outstanding + recovered == principal: post 300000 then reverse returns to origin."""

    def _post_then_reverse(self, api, ctx):
        ra = make_recovery_agent_headers("ra1")
        inst = get_success_data(api.create_installment(ctx["rp_id"], {"amount_cents": 300000}, ra))
        get_success_data(api.reverse_installment(inst["id"], ra))
        return get_success_data(api.get_recovery_plan(ctx["rp_id"],
                                                     TEST_USERS["recovery_agent_headers"]))

    def test_reversal_restores_recovered_and_outstanding(self, api):
        """PRD §3.7: "A reversal is the compensating inverse of a posting: it decreases
        the plan's `recovered_cents` by the installment's `amount_cents` and increases the
        plan's `outstanding_cents` by the same amount, preserving the
        outstanding-plus-recovered invariant."

        Design: Difficulty/compensating_invariant/recovery_principal_conserved_post_then_reverse
        """
        ctx = setup_paid_claim(api, missed_months=5, acceleration_requested=False)
        plan = self._post_then_reverse(api, ctx)
        assert plan["recovered_cents"] == 0, f"expected recovered 0, got {plan['recovered_cents']}"
        assert plan["outstanding_cents"] == 1124995, \
            f"expected outstanding 1124995, got {plan['outstanding_cents']}"

    def test_reversal_keeps_plan_active_and_conserved(self, api):
        """PRD §3.7: "reversal is allowed only while the installment is still `POSTED` and
        only while its parent plan is still `ACTIVE`".
        PRD §3.7: "preserving the outstanding-plus-recovered invariant."

        Design: Difficulty/compensating_invariant/recovery_principal_conserved_post_then_reverse
        """
        ctx = setup_paid_claim(api, missed_months=5, acceleration_requested=False)
        plan = self._post_then_reverse(api, ctx)
        assert plan["status"] == "ACTIVE", f"expected ACTIVE, got {plan['status']}"
        assert_recovery_principal_conserved(plan)


class TestRecoveryAutoSettlement:
    def test_full_installment_settles_plan_and_clears_open_count(self, api):
        """PRD §3.7: "When a posted installment drives `outstanding_cents` to exactly
        zero, the plan is automatically settled — the system moves it from `ACTIVE` to the
        terminal `SETTLED` state and decrements the renter applicant's
        `open_recovery_count` by one."

        Design: Corner/state_machines/recovery_plan_auto_settles_when_fully_recovered
        """
        ctx = setup_paid_claim(api, missed_months=5, acceleration_requested=False)
        get_success_data(api.create_installment(
            ctx["rp_id"], {"amount_cents": 1124995}, make_recovery_agent_headers("ra1")))
        plan = get_success_data(api.get_recovery_plan(ctx["rp_id"],
                                                     TEST_USERS["recovery_agent_headers"]))
        assert plan["outstanding_cents"] == 0
        assert plan["status"] == "SETTLED", f"expected SETTLED, got {plan['status']}"
        applicant = get_success_data(api.get_applicant(ctx["ap_id"],
                                                      TEST_USERS["underwriter_headers"]))
        assert applicant["open_recovery_count"] == 0
