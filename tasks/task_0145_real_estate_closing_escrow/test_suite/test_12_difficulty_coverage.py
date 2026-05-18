"""Additional difficulty-design coverage tests.

Every scaffold_difficulty_design[*].instances[*] entry is covered by at
least TWO tests across the suite. This file adds the second (or third)
test for instances where the first appearance lived in a domain-
specific file. Each test docstring carries # difficulty: <rule>/<name>.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_cd,
    advance_clock_by,
    api_client,
    cancel_escrow,
    confirm_callback_payload,
    create_cd,
    create_wire,
    create_disbursement,
    issue_cd,
    re_get_escrow_file,
    setup_confirmed_wire,
    setup_disbursement_settled,
    setup_emd_held,
    setup_escrow_in_contingent_cd,
    setup_escrow_in_contingent_wire,
    submit_wire,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    version_only_payload,
    with_idempotency,
)


# ===========================================================================
# Cash-to-close rounding-order pin — PRD §3.5
# ===========================================================================
class TestCashToCloseRoundingOrderSecondInstance:

    def test_cash_to_close_with_zero_days_owned(self, api):
        """PRD §3.5: "First, the annual property tax from the parent
        property's tax_annual is multiplied by seller_days_owned and
        divided by the year basis of 365 days (leap years are ignored
        by design); the raw quotient is then rounded half-up to two
        decimal places and recorded as prorated_tax_credit."

        Claim: with seller_days_owned=0, both prorated credits are 0.00
        and cash_to_close reduces to:
          purchase_price - loan_amount - held_emd - seller_credits
          - 0 - 0 + total_loan_costs.
        Concretely with the standard defaults:
          300000 - 240000 - 3000 - 0 - 0 - 0 + 5000 = 62000.00.

        # difficulty: combinatorial_formula/cash_to_close_rounding_order_pin
        """
        bundle = setup_escrow_in_contingent_cd(
            purchase_price=300000.00, loan_amount=240000.00,
            emd_amount=3000.00, hoa_annual_dues=789.0, tax_annual=1234.0,
        )
        cd = create_cd(
            bundle["escrow_file"]["id"],
            total_loan_costs=5000.00,
            seller_credits=0.00,
            seller_days_owned=0,
        )
        assert cd["prorated_tax_credit"] == pytest.approx(0.0, abs=0.001)
        assert cd["prorated_hoa_credit"] == pytest.approx(0.0, abs=0.001)
        assert cd["cash_to_close"] == pytest.approx(62000.00, abs=0.01)


# ===========================================================================
# Wire fraud cascade (rule 4, instance #1) — second test
# ===========================================================================
class TestWireFraudCascadeSecondInstance:

    def test_flag_fraud_from_pending_confirmation_terminal_state(self, api):
        """PRD §3.6: "A PENDING_CONFIRMATION wire can also be flagged
        as fraud, moving it to the terminal REJECTED_FRAUD_FLAG".

        Claim: POST /wire-instructions/{id}/flag-fraud on a
        PENDING_CONFIRMATION wire moves it to REJECTED_FRAUD_FLAG.

        # difficulty: transitive_cascade/wire_fraud_flag_to_disbursement_reverse_to_escrow_stall
        """
        bundle = setup_escrow_in_contingent_wire()
        wire = create_wire(
            bundle["escrow_file"]["id"], "SELLER",
            bundle["seller"]["id"],
        )
        wire = submit_wire(wire["id"], version=wire["version"])
        assert wire["status"] == "PENDING_CONFIRMATION"
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.flag_fraud_wire(
            wire["id"], version_only_payload(version=wire["version"]), eo,
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED_FRAUD_FLAG"


# ===========================================================================
# Priority pair: SoD vs INVALID_STATE on wire confirm — second test
# ===========================================================================
class TestSoDPriorityPairSecondInstance:

    def test_voided_wire_confirm_attempt_returns_invalid_state(self, api):
        """PRD §2.8: "the entity's current state matching the from-
        state required by the requested transition (ERR_INVALID_STATE)
        ... the segregation-of-duties check on wire confirmation and
        disbursement approval (ERR_SOD_VIOLATION)".

        Claim: confirm-callback on a VOIDED wire by the CD issuer (who
        would otherwise SoD-violate) yields ERR_INVALID_STATE, not
        ERR_SOD_VIOLATION (priority 5 wins over priority 7).

        # difficulty: priority_pair_validation_conflict/sod_violation_beats_invalid_state_on_wire_confirm
        """
        bundle = setup_escrow_in_contingent_wire()
        wire = create_wire(
            bundle["escrow_file"]["id"], "SELLER",
            bundle["seller"]["id"],
        )
        # Void it from DRAFT.
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.void_wire_instruction(
            wire["id"], version_only_payload(version=wire["version"]), eo,
        )
        voided = validate_success(resp)
        assert voided["status"] == "VOIDED"
        # CD issuer attempts confirm-callback — SoD violator on a
        # VOIDED row.
        resp = api.confirm_callback_wire(
            voided["id"],
            confirm_callback_payload(
                callback_completed=True,
                callback_channel="VOICE_VERIFIED",
                version=voided["version"],
            ),
            with_idempotency(TEST_USERS["escrow_officer_headers"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Priority pair: CROSS_ENTITY_STATE vs WAITING_PERIOD on CD promote
# — second test
# ===========================================================================
class TestCrossEntityVsTemporalPrioritySecondInstance:

    def test_promote_draft_cd_returns_state_not_temporal(self, api):
        """PRD §2.8 priority order: state-class (priority 5/6) precedes
        business_temporal (priority 9, ERR_CD_WAITING_PERIOD).

        Claim: attempting to promote a CD that is still in DRAFT (never
        ISSUED or ACKNOWLEDGED) returns ERR_INVALID_STATE — not
        ERR_CD_WAITING_PERIOD — because the state-class check fires
        first in the priority order.

        # difficulty: priority_pair_validation_conflict/cross_entity_state_beats_business_temporal_on_cd_promote
        """
        bundle = setup_escrow_in_contingent_cd()
        cd = create_cd(bundle["escrow_file"]["id"])
        assert cd["status"] == "DRAFT"
        eo = with_idempotency(TEST_USERS["escrow_officer_headers"])
        resp = api.promote_closing_disclosure(
            cd["id"], version_only_payload(version=cd["version"]), eo,
        )
        actual = validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
            ],
        )
        # The temporal error must NOT be selected.
        assert actual != ApiErrorId.ERR_CD_WAITING_PERIOD.value
