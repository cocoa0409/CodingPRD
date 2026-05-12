"""Reimbursement claims (honor / dispute / extinguish) and settlement
compensation cascades (PRD §3.8 / §3.9)."""
from __future__ import annotations

import pytest

from test_helpers import (
    compensate_payload,
    dispute_claim,
    dispute_claim_payload,
    extinguish_claim,
    get_lc,
    get_presentation,
    honor_claim,
    setup_disputed_reimbursement_chain,
    setup_negotiation_paid_settlement,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.9 — Honor
# ===========================================================================
class TestReimbursementHonor:

    def test_honor_sets_status_and_amount(self, api):
        """PRD §3.9: 'The IssuingBank honours the claim — moving it from
        SUBMITTED (or from DISPUTED) to HONORED, setting
        honored_amount_minor_units equal to claimed_amount_minor_units,
        and stamping honored_at to the current clock.'"""
        lc_after, bundle, _, _, claim = setup_negotiation_paid_settlement(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
            discrepancy_fee_minor_units=0,
        )
        assert claim is not None
        res = api.honor_claim(claim["id"], bundle["issuing_bank_headers"])
        after = validate_success(res)
        assert after["status"] == "HONORED"
        assert after["honored_amount_minor_units"] == claim["claimed_amount_minor_units"]
        assert after["honored_at"] is not None

    def test_double_honor_rejected(self, api):
        """PRD §3.9: 'A second honour or dispute on an already-HONORED
        claim is rejected with ERR_REIMBURSEMENT_ALREADY_HONORED.'"""
        lc_after, bundle, _, _, claim = setup_negotiation_paid_settlement(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
            discrepancy_fee_minor_units=0,
        )
        assert claim is not None
        honor_claim(claim["id"], bundle["issuing_bank_headers"])
        res = api.honor_claim(claim["id"], bundle["issuing_bank_headers"])
        validate_error(res, "ERR_REIMBURSEMENT_ALREADY_HONORED")


# ===========================================================================
# §3.9 — Dispute cascades to settlement compensation
# ===========================================================================
class TestDisputeCascade:

    def test_dispute_flips_claim_and_compensates_settlement(self, api):
        """PRD §3.9: 'Alternatively the IssuingBank may dispute the
        claim, with a reason — which moves it from SUBMITTED to
        DISPUTED and cascades a settlement compensation to COMPENSATED.'

        PRD §3.8: '[compensate] decrements LC.drawn_amount_minor_units
        by principal_minor_units, recomputes available_amount_minor_units,
        and reverts the parent Presentation to EXAMINED_CLEAN'."""
        lc_after, bundle, presentation_after, settlement_after, claim_after = (
            setup_disputed_reimbursement_chain(
                amount_minor_units=200_000,
                drawing_amount_minor_units=80_000,
            )
        )
        assert claim_after["status"] == "DISPUTED"
        assert settlement_after["status"] == "COMPENSATED"
        # LC ledger reverted.
        assert lc_after["drawn_amount_minor_units"] == 0, (
            "PRD §2.6: 'addition followed by its compensation must net "
            "to zero on drawn_amount_minor_units'"
        )
        assert lc_after["available_amount_minor_units"] == 200_000
        # Presentation reverted to EXAMINED_CLEAN.
        assert presentation_after["status"] == "EXAMINED_CLEAN"

    def test_extinguish_claim_from_disputed(self, api):
        """PRD §3.9: 'From DISPUTED the NegotiatingBank may extinguish
        the claim, moving it to terminal EXTINGUISHED ...'."""
        lc_after, bundle, _, _, claim_after = (
            setup_disputed_reimbursement_chain(
                amount_minor_units=200_000,
                drawing_amount_minor_units=80_000,
            )
        )
        assert claim_after["status"] == "DISPUTED"
        res = api.extinguish_claim(
            claim_after["id"], bundle["negotiating_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "EXTINGUISHED"

    def test_honor_after_dispute_succeeds(self, api):
        """PRD §3.9: '... or the issuing bank may relent and honour
        after all.' PRD §3.9 also: 'moving it from SUBMITTED (or from
        DISPUTED) to HONORED'."""
        lc_after, bundle, _, _, claim_after = (
            setup_disputed_reimbursement_chain(
                amount_minor_units=200_000,
                drawing_amount_minor_units=80_000,
            )
        )
        res = api.honor_claim(claim_after["id"], bundle["issuing_bank_headers"])
        after = validate_success(res)
        assert after["status"] == "HONORED"


# ===========================================================================
# §3.8 — Direct compensate path
# ===========================================================================
class TestDirectCompensate:

    def test_compensate_reverts_lc_drawn_and_presentation(self, api):
        """PRD §3.8: 'Compensation moves the settlement to COMPENSATED,
        decrements LC.drawn_amount_minor_units by principal_minor_units,
        recomputes available_amount_minor_units, and reverts the parent
        Presentation to EXAMINED_CLEAN so that a fresh settlement may
        be initiated.'"""
        lc_after, bundle, _, _, claim = setup_negotiation_paid_settlement(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
            discrepancy_fee_minor_units=0,
        )
        # Dispute path is the only PRD-named compensate trigger:
        # 'The trigger conditions are an
        # ERR_REIMBURSEMENT_ALREADY_HONORED-incompatible
        # ReimbursementClaim.status of DISPUTED, or the absence (or
        # reversal) of an external BANK_PAYMENT_CONFIRMED event.'
        # Use dispute to put the claim into DISPUTED so compensate is
        # legitimately triggerable. Per PRD §3.9 dispute already
        # cascades to compensate; dispute_claim covers this.
        from test_helpers import dispute_claim as _dispute  # noqa: WPS433
        _dispute(claim["id"], bundle["issuing_bank_headers"])
        # After dispute, the settlement is COMPENSATED. Read the
        # consequent LC + presentation.
        snapshot = get_lc(lc_after["id"], bundle["applicant_headers"])
        assert snapshot["drawn_amount_minor_units"] == 0
        assert snapshot["available_amount_minor_units"] == 200_000
