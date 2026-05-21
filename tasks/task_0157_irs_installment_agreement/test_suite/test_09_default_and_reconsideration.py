"""Default → reconsideration → reinstatement cycle.

PRD §3.4 (default), §3.10 (reconsideration). Tests the load-bearing
non-linear state-machine cycle ACTIVE → DEFAULTED → ACTIVE.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    IRS_OFFICER_SHARED_ID,
    advance_clock_to,
    create_and_activate_agreement,
    create_reconsideration_payload,
    create_taxpayer,
    create_tax_liability,
    decide_reconsideration,
    decide_reconsideration_payload,
    default_active_agreement_via_missed_payments,
    get_installment_agreement,
    make_irs_officer_headers,
    make_taxpayer_headers,
    open_reconsideration,
    setup_default_active_via_missed_cycles,
    validate_error,
    validate_success,
)


class TestDefaultCycle:

    def test_three_missed_payments_default_active_agreement(self, api):
        """PRD §3.4: "When missed_payment_count reaches three or more,
        ... the agreement transitions from ACTIVE to DEFAULTED."

        Claim: 3 advances of 31 days + sweep → agreement is DEFAULTED.

        # difficulty: non_linear_state_machine/ia_default_reinstate_cycle
        """
        taxpayer, liability, agreement = (
            setup_default_active_via_missed_cycles()
        )
        assert agreement["status"] == "DEFAULTED"


class TestReconsiderationCycle:

    def test_approved_reconsideration_returns_agreement_to_active(self, api):
        """PRD §3.10: "On approval, if the underlying agreement is
        DEFAULTED, the agreement cascades from DEFAULTED to ACTIVE:
        missed_payment_count is reset to zero."

        Claim: ACTIVE → DEFAULTED (via missed) → APPROVED
        reconsideration (by a different officer) → ACTIVE with
        missed_payment_count == 0.

        # difficulty: non_linear_state_machine/ia_default_reinstate_cycle
        """
        # Use a specific activator id so the reconsideration decider
        # can be a distinct officer per PRD §2.8 segregation of duties.
        activator_id = "irs-officer-activator"
        decider_id = "irs-officer-decider"
        taxpayer, liability, defaulted = (
            setup_default_active_via_missed_cycles(
                activator_id=activator_id,
            )
        )
        assert defaulted["status"] == "DEFAULTED"
        # Open a reconsideration as the taxpayer.
        request = open_reconsideration(
            taxpayer["id"], defaulted["id"], reason="MISSED_PAYMENT_CURE",
        )
        # Decide APPROVED by a different IRSOfficer.
        decide_reconsideration(
            request["id"], "APPROVED", officer_id=decider_id,
        )
        refreshed = get_installment_agreement(defaulted["id"])
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["missed_payment_count"] == 0, (
            "PRD §3.10: 'missed_payment_count is reset to zero' on "
            "reconsideration-approved cure"
        )

    def test_same_officer_decide_blocked_by_segregation_of_duties(self, api):
        """PRD §2.8: "Within the reconsideration pipeline, the
        `IRSOfficer` who originally activated an installment agreement
        cannot be the same operator who later decides a
        reconsideration on that agreement; a mismatched decision
        attempt is rejected with the same `ERR_SEGREGATION_OF_DUTIES`
        code."

        Claim: activator IRSO_A trying to decide the reconsideration
        themselves → ERR_SEGREGATION_OF_DUTIES.
        """
        activator_id = "irs-officer-sod-same"
        taxpayer, liability, defaulted = (
            setup_default_active_via_missed_cycles(
                activator_id=activator_id,
            )
        )
        request = open_reconsideration(
            taxpayer["id"], defaulted["id"], reason="MISSED_PAYMENT_CURE",
        )
        # Same officer attempts to decide.
        resp = api.decide_reconsideration_request(
            request["id"],
            decide_reconsideration_payload("APPROVED"),
            make_irs_officer_headers(activator_id),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_denied_reconsideration_keeps_agreement_defaulted(self, api):
        """PRD §3.10: "On denial, no cascade runs; the agreement remains
        in DEFAULTED."

        Claim: a DENIED reconsideration leaves agreement.status ==
        DEFAULTED.
        """
        activator_id = "irs-officer-denied"
        decider_id = "irs-officer-denied-decider"
        taxpayer, liability, defaulted = (
            setup_default_active_via_missed_cycles(
                activator_id=activator_id,
            )
        )
        request = open_reconsideration(
            taxpayer["id"], defaulted["id"], reason="INCOME_CHANGE",
        )
        decide_reconsideration(
            request["id"], "DENIED", officer_id=decider_id,
        )
        refreshed = get_installment_agreement(defaulted["id"])
        assert refreshed["status"] == "DEFAULTED"


class TestStatePrecedenceOverFiscal:

    def test_state_check_wins_over_overpayment(self, api):
        """PRD §2.10: "State preconditions come next: general status
        check (priority 6) returns ERR_INVALID_STATE."
        PRD §2.10: "the fiscal band at priorities 20–21 (overpayment,
        revival of fully-resolved agreements)."

        Claim: an installment payment with a too-large amount_cents
        against a DEFAULTED agreement is rejected with ERR_INVALID_STATE
        (state precedence: 6 < 20), not ERR_OVERPAYMENT.

        # difficulty: priority_pair_validation_conflict/state_vs_business_fiscal_overpayment
        """
        from test_helpers import (
            TEST_USERS,
            record_installment_payment_payload,
        )
        activator_id = "irs-officer-priority-state"
        taxpayer, liability, defaulted = (
            setup_default_active_via_missed_cycles(
                activator_id=activator_id,
                liability_amount_cents=200_000,
            )
        )
        # Attempt a 5_000_000-cent payment against a defaulted IA whose
        # remaining balance is below 5_000_000 — both ERR_INVALID_STATE
        # (state) and ERR_OVERPAYMENT (fiscal) would apply. The state
        # check has higher priority.
        resp = api.record_installment_payment(
            defaulted["id"],
            record_installment_payment_payload(
                amount_cents=5_000_000,
                received_at="2020-06-01T00:00:00.000Z",
            ),
            TEST_USERS["irs_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
