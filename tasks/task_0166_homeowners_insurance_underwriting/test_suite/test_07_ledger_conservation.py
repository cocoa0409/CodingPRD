"""Compensating invariants: an endorsement apply/remove pair and a lapse/reinstate
cycle both conserve the policy's premium ledger. Queue A — rule compensating_invariant.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_underwriter_headers,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestEndorsementApplyRemoveConserved:
    def _active_policy_with_applied_endorsement(self, api):
        """ACTIVE policy: binding payment 997.50 settled, one APPLIED WATER_BACKUP
        endorsement (+80). premium_balance after payment = 1077.50."""
        ctx = fx.setup_bound_policy(
            requested_coverage_a=300000, wind_hail_deductible_pct=2,
            endorsements=[("PERIL_ADD", "WATER_BACKUP", 20000)],
        )
        policy = ctx["policy"]
        # Pay only the base premium 997.50 (binding payment must equal annual_premium,
        # which is copied from the quote = base 997.50 + endorsement 80.00 = 1077.50).
        fx.pay_binding(policy["id"], policy["annual_premium"])
        return ctx

    def test_remove_applied_endorsement_restores_premium_balance(self, api):
        """PRD §2.8: "every action that posts to the ledger and is later reversed must
        be backed by a compensating posting of equal magnitude and opposite sign, so
        that a forward posting plus its reversal nets to zero change in
        `premium_balance`."
        PRD §3.7: "for a removed peril-add the reversal is a CREDIT for its
        `premium_delta` ... `premium_balance` is recomputed afterward."

        Design: Difficulty/compensating_invariant/endorsement_apply_then_remove_premium_balance_conserved
        """
        ctx = self._active_policy_with_applied_endorsement(api)
        policy, uw = ctx["policy"], ctx["underwriter"]
        e1 = ctx["endorsements"][0]
        before = fx.get_policy(policy["id"])
        # annual_premium = 1077.50 (base 997.50 + endorsement 80.00); after binding
        # payment of 1077.50 the balance is 80.00 (endorsement) + 1077.50 (binding).
        bal_before = before["premium_balance"]
        validate_success(api.remove_endorsement(e1["id"], make_underwriter_headers(uw["id"])))
        after = fx.get_policy(policy["id"])
        assert after["premium_balance"] == round(bal_before - 80.00, 2), (
            f"Removing the +80.00 PERIL_ADD must credit exactly 80.00: "
            f"{bal_before} -> {after['premium_balance']}"
        )

    def test_remove_applied_endorsement_reverses_total_insured_value(self, api):
        """PRD §3.7: "Removing a peril-add also lowers the property's
        `total_insured_value` by that endorsement's `coverage_limit`. Because the
        reversal exactly offsets the original posting, the balance and the total
        insured value land precisely where they would have been had the endorsement
        never applied."

        Design: Difficulty/compensating_invariant/endorsement_apply_then_remove_premium_balance_conserved
        """
        ctx = self._active_policy_with_applied_endorsement(api)
        policy, uw, prop = ctx["policy"], ctx["underwriter"], ctx["property"]
        e1 = ctx["endorsements"][0]
        tiv_before = fx.get_property(prop["id"])["total_insured_value"]
        assert tiv_before == 294200.00
        validate_success(api.remove_endorsement(e1["id"], make_underwriter_headers(uw["id"])))
        tiv_after = fx.get_property(prop["id"])["total_insured_value"]
        assert tiv_after == 274200.00, (
            f"coverage_limit 20000 reversed: {tiv_before} -> {tiv_after}"
        )


class TestLapseReinstateLedgerReconstructed:
    def test_lapse_writeoff_zeros_balance(self, api):
        """PRD §3.7: "A lapse moves the policy to `LAPSED`, increases its `lapse_count`
        by one, increments the policy's `version` by one, and posts a CREDIT to the
        ledger for the entire current `premium_balance` as a lapse write-off, so that
        `premium_balance` returns to 0."

        Design: Difficulty/compensating_invariant/lapse_writeoff_then_reinstate_balance_reconstructed
        """
        ctx = fx.setup_active_policy(binding_amount=997.50)
        policy, uw = ctx["policy"], ctx["underwriter"]
        assert policy["premium_balance"] == 997.50
        lapsed = validate_success(
            api.lapse_policy(policy["id"], {"expected_policy_version": policy["version"]},
                             make_underwriter_headers(uw["id"]))
        )
        assert lapsed["status"] == "LAPSED" and lapsed["lapse_count"] == 1
        assert lapsed["premium_balance"] == 0.00, (
            f"LAPSE_WRITEOFF credit must zero the balance, got {lapsed['premium_balance']}"
        )

    def test_reinstatement_redebits_premium_plus_fee(self, api):
        """PRD §3.7: "On success the policy becomes `REINSTATED`, and the system posts
        two DEBITs to the ledger — one for the `annual_premium` as a re-billed binding
        premium and one for the 250 dollar reinstatement fee — recomputing
        `premium_balance`."

        Design: Difficulty/compensating_invariant/lapse_writeoff_then_reinstate_balance_reconstructed
        """
        ctx = fx.setup_active_policy(binding_amount=997.50)
        policy, uw = ctx["policy"], ctx["underwriter"]
        fx.lapse_policy(policy["id"], policy["version"], uw["id"])
        validate_success(
            api.create_payment(
                f.create_payment_payload(policy["id"], "REINSTATEMENT", 1247.50), AGENT
            ),
            201,
        )
        after = fx.get_policy(policy["id"])
        assert after["status"] == "REINSTATED"
        assert after["premium_balance"] == 1247.50, (
            f"annual_premium 997.50 + REINSTATEMENT_FEE 250.00 re-debited, "
            f"got {after['premium_balance']}"
        )
