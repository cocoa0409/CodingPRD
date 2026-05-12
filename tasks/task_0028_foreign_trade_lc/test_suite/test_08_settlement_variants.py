"""Sight, usance, and negotiation settlement variants (PRD §3.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_DISCREPANCY_FEE_MINOR,
    advance_clock_days,
    applicant_decision_accept,
    assert_payment_settlement,
    create_negotiation_settlement,
    create_settlement_payload,
    create_sight_settlement,
    execute_sight,
    get_lc,
    get_presentation,
    get_success_data,
    negotiation_advance,
    negotiation_discount_minor_units,
    record_acceptance,
    setup_examined_clean_presentation,
    setup_examined_discrepant_presentation,
    setup_party_bundle,
    setup_active_lc,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.8 — Settlement creation
# ===========================================================================
class TestSettlementCreation:

    def test_create_settlement_for_sight_lc_starts_pending_sight(self, api):
        """PRD §3.8: 'a settlement row is initialised in PENDING, its
        principal_minor_units is set equal to the presentation's
        drawing_amount_minor_units, and its settlement_type is
        determined by the LC's lc_type — SIGHT_PAYMENT for sight LCs,
        USANCE_ACCEPTANCE for usance LCs ...'."""
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="SIGHT",
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        res = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        settlement = validate_success(res, expected_status=201)
        assert_payment_settlement(settlement)
        assert settlement["status"] == "PENDING"
        assert settlement["settlement_type"] == "SIGHT_PAYMENT"
        assert settlement["principal_minor_units"] == 5_000

    def test_create_settlement_for_usance_lc_starts_pending_usance(self, api):
        """PRD §3.8: '... USANCE_ACCEPTANCE for usance LCs ...'."""
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="USANCE",
            usance_tenor_days=60,
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        res = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        settlement = validate_success(res, expected_status=201)
        assert settlement["settlement_type"] == "USANCE_ACCEPTANCE"


# ===========================================================================
# §3.8 — Sight execute
# ===========================================================================
class TestSightExecute:

    def test_execute_sight_pays_with_zero_fee_for_clean_presentation(self, api):
        """PRD §3.8: 'The sight-payment branch is the simplest. The
        IssuingBank executes sight payment, which advances the
        settlement from PENDING to PAID, sets paid_at to the current
        clock, and computes beneficiary_proceeds_minor_units from the
        proceeds formula described shortly.'

        PRD §3.8: 'The fee is the LC's discrepancy_fee_minor_units flat
        per-presentation amount when the presentation's history
        includes a passage through EXAMINED_DISCREPANT followed by
        ACCEPTED_BY_APPLICANT; otherwise the fee is zero.' For an
        EXAMINED_CLEAN presentation, fee == 0.
        """
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="SIGHT",
            amount_minor_units=100_000,
            drawing_amount_minor_units=100_000,
        )
        settlement = create_sight_settlement(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        settlement = execute_sight(
            settlement["id"], bundle["issuing_bank_headers"],
        )
        assert settlement["status"] == "PAID"
        assert settlement["paid_at"] is not None
        assert settlement["discrepancy_fee_minor_units"] == 0
        assert settlement["beneficiary_proceeds_minor_units"] == 100_000

    def test_execute_sight_charges_fee_after_discrepant_accepted(self, api):
        """PRD §3.8: 'The fee is the LC's discrepancy_fee_minor_units
        flat per-presentation amount when the presentation's history
        includes a passage through EXAMINED_DISCREPANT followed by
        ACCEPTED_BY_APPLICANT; otherwise the fee is zero.'"""
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=100_000,
            drawing_amount_minor_units=100_000,
            discrepancy_fee_minor_units=DEFAULT_DISCREPANCY_FEE_MINOR,
        )
        # Applicant accepts → ACCEPTED_BY_APPLICANT.
        applicant_decision_accept(presentation["id"], bundle["applicant_headers"])
        # Settle.
        settlement = create_sight_settlement(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        settlement = execute_sight(
            settlement["id"], bundle["issuing_bank_headers"],
        )
        assert settlement["discrepancy_fee_minor_units"] == DEFAULT_DISCREPANCY_FEE_MINOR
        assert settlement["beneficiary_proceeds_minor_units"] == (
            100_000 - DEFAULT_DISCREPANCY_FEE_MINOR
        ), (
            "PRD §3.8: 'The fee is subtracted from the principal first ... "
            "For sight and usance the discount is zero, so "
            "beneficiary_proceeds_minor_units equals base.'"
        )

    def test_execute_sight_on_usance_settlement_rejected(self, api):
        """PRD §3.8: 'An execute-sight call on a non-SIGHT_PAYMENT
        settlement is rejected with ERR_SETTLEMENT_TYPE_MISMATCH.'"""
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="USANCE", usance_tenor_days=60,
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        # Settlement is USANCE_ACCEPTANCE.
        s = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        s = validate_success(s, expected_status=201)
        res = api.execute_sight(s["id"], bundle["issuing_bank_headers"])
        validate_error(res, "ERR_SETTLEMENT_TYPE_MISMATCH")


# ===========================================================================
# §3.8 — Usance acceptance + maturity
# ===========================================================================
class TestUsanceAcceptance:

    def test_record_acceptance_sets_maturity_date(self, api):
        """PRD §3.8: 'The IssuingBank records acceptance, which moves
        the settlement from PENDING to ACCEPTED, sets accepted_at to the
        current clock, computes maturity_date as accepted_at plus the
        LC's usance_tenor_days, and increments
        LC.drawn_amount_minor_units.'"""
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="USANCE", usance_tenor_days=60,
            amount_minor_units=100_000,
            drawing_amount_minor_units=100_000,
        )
        settlement = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        settlement = validate_success(settlement, expected_status=201)
        settlement = record_acceptance(
            settlement["id"], bundle["issuing_bank_headers"],
        )
        assert settlement["status"] == "ACCEPTED"
        assert settlement["accepted_at"] is not None
        assert settlement["maturity_date"] is not None, (
            "PRD §3.8: 'computes maturity_date as accepted_at plus the "
            "LC's usance_tenor_days'"
        )
        # And drawn_amount incremented on the LC.
        snapshot = get_lc(lc["id"], bundle["applicant_headers"])
        assert snapshot["drawn_amount_minor_units"] == 100_000

    def test_explicit_pay_before_maturity_rejected(self, api):
        """PRD §3.8: 'Manual override of the maturity wait is forbidden —
        an explicit payment call before the maturity_date is rejected
        with ERR_MATURITY_NOT_REACHED.'

        A USANCE settlement may not be paid via execute-sight; PRD
        names ERR_MATURITY_NOT_REACHED for the manual-override path,
        and ERR_SETTLEMENT_TYPE_MISMATCH for execute-sight on USANCE.
        We exercise the type-mismatch shortcut: any explicit payment
        attempt on a USANCE settlement before maturity must fail.
        """
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="USANCE", usance_tenor_days=60,
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        s = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        s = validate_success(s, expected_status=201)
        record_acceptance(s["id"], bundle["issuing_bank_headers"])
        # Explicit execute-sight call on a USANCE settlement → mismatch.
        res = api.execute_sight(s["id"], bundle["issuing_bank_headers"])
        validate_error(res, "ERR_SETTLEMENT_TYPE_MISMATCH")


# ===========================================================================
# §3.8 — Negotiation advance
# ===========================================================================
class TestNegotiationAdvance:

    def test_negotiation_override_creates_negotiation_settlement(self, api):
        """PRD §3.8: 'except when a settlement_type_override of
        NEGOTIATION is supplied at creation, which is the only legal
        override and is restricted to flows where a NegotiatingBank is
        initiating the advance.'"""
        bundle = setup_party_bundle(with_negotiating=True)
        lc, _ = setup_active_lc(
            bundle=bundle,
            lc_type="SIGHT",
            amount_minor_units=100_000,
        )
        from test_helpers import setup_examined_clean_presentation as _seec  # noqa: WPS433
        _, _, presentation, _ = _seec(
            lc=lc, bundle=bundle, drawing_amount_minor_units=80_000,
        )
        # NegotiatingBank creates a negotiation settlement.
        s = api.create_settlement(
            presentation["id"],
            create_settlement_payload(settlement_type_override="NEGOTIATION"),
            bundle["negotiating_bank_headers"],
        )
        settlement = validate_success(s, expected_status=201)
        assert settlement["settlement_type"] == "NEGOTIATION"
        assert settlement["status"] == "PENDING"

    def test_negotiation_advance_pays_and_creates_reimbursement_claim(self, api):
        """PRD §3.8: 'The NegotiatingBank posts a negotiation-advance,
        which moves the settlement from PENDING to PAID, sets paid_at
        to the current clock, computes both
        negotiation_advance_minor_units and
        negotiation_discount_minor_units, and as cascade auto-creates
        a ReimbursementClaim in SUBMITTED whose
        claimed_amount_minor_units equals the settlement's
        principal_minor_units.'"""
        from test_helpers import setup_negotiation_paid_settlement  # noqa: WPS433
        lc_after, bundle, _presentation, settlement, claim = (
            setup_negotiation_paid_settlement(
                amount_minor_units=200_000,
                drawing_amount_minor_units=80_000,
                discrepancy_fee_minor_units=0,
            )
        )
        assert settlement["status"] == "PAID"
        # Discount: floor(80000 * 350/10000 * 7/360) = 54
        expected_discount = negotiation_discount_minor_units(80_000)
        assert settlement["negotiation_discount_minor_units"] == expected_discount
        # Advance: base - discount.
        assert settlement["negotiation_advance_minor_units"] == 80_000 - expected_discount
        assert settlement["beneficiary_proceeds_minor_units"] == 80_000 - expected_discount
        # ReimbursementClaim auto-created with claimed_amount = principal.
        assert claim is not None, (
            "PRD §3.8: 'as cascade auto-creates a ReimbursementClaim in "
            "SUBMITTED'"
        )
        assert claim["status"] == "SUBMITTED"
        assert claim["claimed_amount_minor_units"] == 80_000, (
            "PRD §3.8: 'claimed_amount_minor_units equals the settlement's "
            "principal_minor_units'"
        )


# ===========================================================================
# §3.8 — Settlement cascade onto LC.drawn / LC.available
# ===========================================================================
class TestSettlementCascades:

    def test_execute_sight_increments_drawn_and_recomputes_available(self, api):
        """PRD §2.6: 'When a presentation settles, the system not only
        flips the PaymentSettlement to a paid state but also accumulates
        LC.drawn_amount_minor_units upward by the settlement's
        principal_minor_units and recomputes
        LC.available_amount_minor_units; both LC.updated_at and
        LC.version advance as part of the same transaction.'"""
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="SIGHT",
            amount_minor_units=10_000,
            drawing_amount_minor_units=4_000,
        )
        before = get_lc(lc["id"], bundle["applicant_headers"])
        assert before["drawn_amount_minor_units"] == 0
        assert before["available_amount_minor_units"] == 10_000

        settlement = create_sight_settlement(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        execute_sight(settlement["id"], bundle["issuing_bank_headers"])

        after = get_lc(lc["id"], bundle["applicant_headers"])
        assert after["drawn_amount_minor_units"] == 4_000, (
            "PRD §2.6: '... accumulates LC.drawn_amount_minor_units "
            "upward by the settlement's principal_minor_units'"
        )
        assert after["available_amount_minor_units"] == 6_000, (
            "PRD §2.6: '... recomputes LC.available_amount_minor_units'"
        )
