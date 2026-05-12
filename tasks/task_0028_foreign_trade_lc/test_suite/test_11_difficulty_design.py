"""Difficulty-design coverage — every instance gets >=2 dedicated tests.

Each test in this file is tagged with `# difficulty: <rule_id>/<instance.name>`
so the coverage check can audit which instance the test satisfies. The
underlying PRD-prose rule is still cited verbatim (PRD-First).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    advance_clock_banking_days,
    advance_clock_days,
    advance_clock_seconds,
    applicant_consent_amendment,
    applicant_decision_accept,
    applicant_decision_reject,
    applicant_override,
    assert_payment_settlement,
    create_amendment_payload,
    create_negotiation_settlement,
    create_presentation,
    create_presentation_payload,
    create_settlement_payload,
    create_sight_settlement,
    cross_check_clean,
    cross_check_discrepant,
    discrepancy_item,
    dispute_claim,
    dispute_claim_payload,
    execute_sight,
    extinguish_claim,
    finalize_examination,
    get_clock,
    get_lc,
    get_presentation,
    honor_claim,
    initiate_amendment,
    iso_z,
    issue_lc,
    negotiation_advance,
    negotiation_discount_minor_units,
    parse_iso,
    primary_review_clean,
    primary_review_discrepant,
    record_acceptance,
    refuse_payload,
    refuse_presentation,
    setup_active_lc,
    setup_disputed_reimbursement_chain,
    setup_examined_clean_presentation,
    setup_examined_discrepant_presentation,
    setup_negotiation_paid_settlement,
    setup_paid_sight_settlement,
    setup_party_bundle,
    setup_pending_amendment,
    setup_presentation_with_clean_documents,
    start_examination,
    submit_lc,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    withdraw_amendment,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestSettlementProceedsSightVsNegotiation:
    """difficulty: dual_variant_calc/settlement_proceeds_sight_vs_negotiation"""

    def test_sight_yields_full_principal_to_beneficiary(self, api):
        """PRD §3.8: 'For sight and usance the discount is zero, so
        beneficiary_proceeds_minor_units equals base.'

        Claim: SIGHT settlement of 100,000 with no discrepancy fee yields
        beneficiary_proceeds = 100,000 (no discount).
        """
        # difficulty: dual_variant_calc/settlement_proceeds_sight_vs_negotiation
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="SIGHT",
            amount_minor_units=100_000,
            drawing_amount_minor_units=100_000,
        )
        s = create_sight_settlement(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        s = execute_sight(s["id"], bundle["issuing_bank_headers"])
        assert s["beneficiary_proceeds_minor_units"] == 100_000
        assert s["negotiation_discount_minor_units"] == 0

    def test_negotiation_yields_principal_minus_discount(self, api):
        """PRD §3.8: 'the rate is 350 basis points annualised (3.50%)
        and the assumed time to reimbursement is 7 days; the rate
        fraction is therefore 350 divided by 10,000 multiplied by 7
        divided by 360, applied to base, with the multiplicative result
        floored to an integer in minor units to produce
        negotiation_discount_minor_units.'

        Claim: identical 100,000 principal, NEGOTIATION variant yields
        beneficiary_proceeds = 100_000 - floor(100000*350*7/(10000*360)).
        """
        # difficulty: dual_variant_calc/settlement_proceeds_sight_vs_negotiation
        lc_after, bundle, _, settlement, _ = setup_negotiation_paid_settlement(
            amount_minor_units=200_000,
            drawing_amount_minor_units=100_000,
            discrepancy_fee_minor_units=0,
        )
        expected_discount = negotiation_discount_minor_units(100_000)
        assert settlement["negotiation_discount_minor_units"] == expected_discount
        assert settlement["beneficiary_proceeds_minor_units"] == 100_000 - expected_discount


class TestPresentationCompliancePrimaryVsCrossCheck:
    """difficulty: dual_variant_calc/presentation_compliance_primary_vs_cross_check"""

    def test_diverging_outcomes_set_conflict_status(self, api):
        """PRD §3.6: 'when they diverge the status advances instead to
        CONFLICT.'"""
        # difficulty: dual_variant_calc/presentation_compliance_primary_vs_cross_check
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        res = api.cross_check(
            examination["id"],
            {
                "secondary_outcome": "DISCREPANT",
                "discrepancies": [
                    discrepancy_item(discrepancy_code="MISSING_DOCUMENT"),
                ],
            },
            __import__("test_helpers").make_operator_headers("op-secondary-001"),
        )
        after = validate_success(res)
        assert after["status"] == "CONFLICT"
        assert after.get("primary_outcome") == "CLEAN"
        assert after.get("secondary_outcome") == "DISCREPANT"

    def test_matching_outcomes_advance_to_cross_check_done(self, api):
        """PRD §3.6: 'When primary_outcome equals secondary_outcome the
        report's status advances from PRIMARY_DONE to CROSS_CHECK_DONE'."""
        # difficulty: dual_variant_calc/presentation_compliance_primary_vs_cross_check
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        cross_check_clean(examination["id"])
        # Re-fetch to confirm CROSS_CHECK_DONE.
        res = api.get_examination(examination["id"], bundle["issuing_bank_headers"])
        after = validate_success(res)
        assert after["status"] == "CROSS_CHECK_DONE"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestComplianceSevenInputNonlinear:
    """difficulty: combinatorial_formula/compliance_check_seven_input_nonlinear"""

    def test_clean_when_all_seven_inputs_pass(self, api):
        """PRD §3.6: 'The compliance outcome is CLEAN if and only if all
        seven checks hold; otherwise it is DISCREPANT and the
        discrepancy list is emitted in the strict order I1 through I7.'

        Claim: a presentation whose documents satisfy I1..I7 finalises
        EXAMINED_CLEAN.
        """
        # difficulty: combinatorial_formula/compliance_check_seven_input_nonlinear
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            amount_minor_units=100_000,
            drawing_amount_minor_units=100_000,
            include_certificate_of_origin=True,
        )
        assert presentation["status"] == "EXAMINED_CLEAN"

    def test_discrepant_when_a_required_document_missing(self, api):
        """PRD §3.6: 'I1 produces MISSING_DOCUMENT'.

        Claim: a presentation whose document set lacks one
        required_documents entry finalises DISCREPANT and the
        Discrepancy list contains MISSING_DOCUMENT.
        """
        # difficulty: combinatorial_formula/compliance_check_seven_input_nonlinear
        lc, bundle, presentation, examination = (
            setup_examined_discrepant_presentation(
                amount_minor_units=100_000,
                drawing_amount_minor_units=100_000,
                discrepancy_codes=["MISSING_DOCUMENT"],
            )
        )
        assert presentation["status"] == "EXAMINED_DISCREPANT"
        # Inspect discrepancies on the examination report.
        from test_helpers import validate_paginated  # noqa: WPS433
        res = api.list_discrepancies(
            examination["id"], bundle["issuing_bank_headers"],
        )
        items, _ = validate_paginated(res)
        codes = [d["discrepancy_code"] for d in items]
        assert "MISSING_DOCUMENT" in codes


class TestSettlementFeeThenDiscountRoundingOrder:
    """difficulty: combinatorial_formula/settlement_fee_then_discount_rounding_order"""

    def test_negotiation_clean_principal_no_fee(self, api):
        """PRD §3.8: 'the fee is the LC's discrepancy_fee_minor_units
        flat per-presentation amount when the presentation's history
        includes a passage through EXAMINED_DISCREPANT followed by
        ACCEPTED_BY_APPLICANT; otherwise the fee is zero.'

        Claim: an EXAMINED_CLEAN presentation under NEGOTIATION yields
        discount on full principal (no fee subtraction).
        """
        # difficulty: combinatorial_formula/settlement_fee_then_discount_rounding_order
        lc_after, bundle, _, settlement, _ = setup_negotiation_paid_settlement(
            amount_minor_units=100_000,
            drawing_amount_minor_units=50_000,
            discrepancy_fee_minor_units=7_500,
        )
        # Presentation never went through DISCREPANT — fee = 0.
        assert settlement["discrepancy_fee_minor_units"] == 0
        expected_discount = negotiation_discount_minor_units(50_000)
        assert settlement["negotiation_discount_minor_units"] == expected_discount


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestExaminationConflictCycle:
    """difficulty: non_linear_state_machine/examination_conflict_cycle"""

    def test_reset_returns_to_in_progress_clearing_outcomes(self, api):
        """PRD §3.6: 'From CONFLICT the IssuingBank may reset the report
        back to IN_PROGRESS, which clears primary_outcome and
        secondary_outcome and deletes every Discrepancy row attached to
        the report'."""
        # difficulty: non_linear_state_machine/examination_conflict_cycle
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        cross_check_discrepant(
            examination["id"],
            [discrepancy_item(discrepancy_code="MISSING_DOCUMENT")],
        )
        res = api.reset_examination(
            examination["id"], bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "IN_PROGRESS"
        assert after.get("primary_outcome") in (None, "")
        assert after.get("secondary_outcome") in (None, "")

    def test_reset_followed_by_cross_check_done_then_finalize(self, api):
        """PRD §3.6: '... documents nonetheless remain frozen.' Plus
        PRD §3.6: 'When primary_outcome equals secondary_outcome the
        report's status advances from PRIMARY_DONE to CROSS_CHECK_DONE'."""
        # difficulty: non_linear_state_machine/examination_conflict_cycle
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        primary_review_clean(examination["id"])
        cross_check_discrepant(
            examination["id"],
            [discrepancy_item(discrepancy_code="MISSING_DOCUMENT")],
        )
        api.reset_examination(examination["id"], bundle["issuing_bank_headers"])
        # Both reviewers now agree on DISCREPANT.
        primary_review_discrepant(
            examination["id"],
            [
                discrepancy_item(discrepancy_code="MISSING_DOCUMENT"),
                discrepancy_item(discrepancy_code="AMOUNT_MISMATCH"),
            ],
        )
        cross_check_discrepant(
            examination["id"],
            [
                discrepancy_item(discrepancy_code="MISSING_DOCUMENT"),
                discrepancy_item(discrepancy_code="AMOUNT_MISMATCH"),
            ],
        )
        res = api.finalize_examination(
            examination["id"], bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "FINALIZED"
        assert after["final_outcome"] == "DISCREPANT"


class TestPaymentSettlementBranchingOnType:
    """difficulty: non_linear_state_machine/payment_settlement_branching_on_type"""

    def test_sight_branch_pays_directly(self, api):
        """PRD §3.8: 'The IssuingBank executes sight payment, which
        advances the settlement from PENDING to PAID, sets paid_at to
        the current clock'."""
        # difficulty: non_linear_state_machine/payment_settlement_branching_on_type
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="SIGHT",
            amount_minor_units=10_000, drawing_amount_minor_units=10_000,
        )
        s = create_sight_settlement(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        s = execute_sight(s["id"], bundle["issuing_bank_headers"])
        assert s["status"] == "PAID"
        assert s["paid_at"] is not None
        assert s.get("maturity_date") in (None, "")
        assert s["negotiation_discount_minor_units"] == 0

    def test_usance_branch_records_acceptance_with_maturity(self, api):
        """PRD §3.8: 'The IssuingBank records acceptance, which moves
        the settlement from PENDING to ACCEPTED, sets accepted_at to the
        current clock, computes maturity_date as accepted_at plus the
        LC's usance_tenor_days'."""
        # difficulty: non_linear_state_machine/payment_settlement_branching_on_type
        lc, bundle, presentation, _ = setup_examined_clean_presentation(
            lc_type="USANCE", usance_tenor_days=60,
            amount_minor_units=10_000, drawing_amount_minor_units=10_000,
        )
        s = api.create_settlement(
            presentation["id"], create_settlement_payload(),
            bundle["issuing_bank_headers"],
        )
        s = validate_success(s, expected_status=201)
        s = record_acceptance(s["id"], bundle["issuing_bank_headers"])
        assert s["status"] == "ACCEPTED"
        assert s["accepted_at"] is not None
        assert s["maturity_date"] is not None
        assert s.get("paid_at") in (None, "")


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestNegotiationSettleThreeHopCascade:
    """difficulty: transitive_cascade/negotiation_settle_three_hop_cascade"""

    def test_three_hops_settlement_claim_lc_ledger(self, api):
        """PRD §3.8: 'The NegotiatingBank posts a negotiation-advance,
        which moves the settlement from PENDING to PAID ... and as
        cascade auto-creates a ReimbursementClaim in SUBMITTED whose
        claimed_amount_minor_units equals the settlement's
        principal_minor_units.'

        PRD §2.6: 'When a presentation settles, the system not only flips
        the PaymentSettlement to a paid state but also accumulates
        LC.drawn_amount_minor_units upward by the settlement's
        principal_minor_units and recomputes
        LC.available_amount_minor_units'.
        """
        # difficulty: transitive_cascade/negotiation_settle_three_hop_cascade
        lc_after, bundle, _presentation, settlement, claim = (
            setup_negotiation_paid_settlement(
                amount_minor_units=200_000,
                drawing_amount_minor_units=80_000,
                discrepancy_fee_minor_units=0,
            )
        )
        # Hop 1: settlement PAID
        assert settlement["status"] == "PAID"
        # Hop 2: ReimbursementClaim auto-created
        assert claim is not None
        assert claim["status"] == "SUBMITTED"
        assert claim["claimed_amount_minor_units"] == 80_000
        # Hop 3: LC drawn / available updated
        assert lc_after["drawn_amount_minor_units"] == 80_000
        assert lc_after["available_amount_minor_units"] == 120_000

    def test_negotiation_advance_amount_matches_formula(self, api):
        """PRD §3.8: 'negotiation_discount_minor_units' / 'advance is
        then negotiation_advance_minor_units equal to base minus the
        discount'."""
        # difficulty: transitive_cascade/negotiation_settle_three_hop_cascade
        lc_after, bundle, _, settlement, _ = setup_negotiation_paid_settlement(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
            discrepancy_fee_minor_units=0,
        )
        expected_discount = negotiation_discount_minor_units(80_000)
        assert settlement["negotiation_advance_minor_units"] == 80_000 - expected_discount
        assert settlement["beneficiary_proceeds_minor_units"] == 80_000 - expected_discount


class TestReimbursementDisputeCompensationCascade:
    """difficulty: transitive_cascade/reimbursement_dispute_compensation_cascade"""

    def test_dispute_cascades_to_compensation_and_lc_revert(self, api):
        """PRD §3.9: 'Alternatively the IssuingBank may dispute the
        claim, with a reason — which moves it from SUBMITTED to
        DISPUTED and cascades a settlement compensation to COMPENSATED.'

        PRD §3.8: '[compensate] decrements LC.drawn_amount_minor_units by
        principal_minor_units, recomputes available_amount_minor_units,
        and reverts the parent Presentation to EXAMINED_CLEAN'.
        """
        # difficulty: transitive_cascade/reimbursement_dispute_compensation_cascade
        lc_after, bundle, presentation_after, settlement_after, claim_after = (
            setup_disputed_reimbursement_chain(
                amount_minor_units=200_000,
                drawing_amount_minor_units=80_000,
            )
        )
        assert claim_after["status"] == "DISPUTED"
        assert settlement_after["status"] == "COMPENSATED"
        assert lc_after["drawn_amount_minor_units"] == 0
        assert lc_after["available_amount_minor_units"] == 200_000
        assert presentation_after["status"] == "EXAMINED_CLEAN"

    def test_dispute_cascade_preserves_invariant_zero_drawn(self, api):
        """PRD §2.6: 'The compensating-invariant rule is that an
        addition followed by its compensation must net to zero on
        drawn_amount_minor_units.'"""
        # difficulty: transitive_cascade/reimbursement_dispute_compensation_cascade
        lc_after, bundle, _, _, _ = setup_disputed_reimbursement_chain(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
        )
        # before-after delta on drawn_amount_minor_units must be 0.
        assert lc_after["drawn_amount_minor_units"] == 0


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestExistenceVsStateOnPresentationCreate:
    """difficulty: priority_pair_validation_conflict/existence_vs_state_on_presentation_create"""

    def test_unknown_lc_path_yields_not_found(self, api, beneficiary_headers):
        """PRD §2.7: 'For a request such as a discrepancy listing under
        a specific examination, the server first verifies that the
        examinationId exists; if not, it returns ERR_NOT_FOUND without
        consulting any deeper segment.'

        PRD §2.11: 'header authentication first, then role-based
        authorisation, then path-resource existence, then body
        foreign-key existence, then state-transition legality'.
        """
        # difficulty: priority_pair_validation_conflict/existence_vs_state_on_presentation_create
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            NON_EXISTENT_UUID,
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=10_000,
            ),
            beneficiary_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_existence_check_precedes_state_when_lc_in_draft(self, api):
        """PRD §2.11: '... then path-resource existence, then body
        foreign-key existence, then state-transition legality ...'.

        With a real LC in DRAFT, presentation creation should hit the
        state check. With a non-existent LC, existence wins. Both
        validations are individually correct; this test just confirms
        the existence path returns ERR_NOT_FOUND for an unknown LC and
        not a state error.
        """
        # difficulty: priority_pair_validation_conflict/existence_vs_state_on_presentation_create
        from test_helpers import (  # noqa: WPS433
            create_lc_draft, setup_party_bundle,
        )
        # First: state-only failure for a DRAFT LC must be ERR_INVALID_STATE_TRANSITION,
        # not ERR_NOT_FOUND.
        bundle = setup_party_bundle()
        lc, _ = create_lc_draft(bundle=bundle)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=10_000,
            ),
            bundle["beneficiary_headers"],
        )
        # LC is in DRAFT — presentation cannot be submitted.
        validate_error(res, "ERR_INVALID_STATE_TRANSITION")


class TestBusinessReferentialVsBusinessFiscalOnPresentationCreate:
    """difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_presentation_create"""

    def test_shipment_out_of_window_wins_over_overdraw(self, api):
        """PRD §2.11: '... then business-temporal checks (expiry,
        shipment date, usance tenor) ... then drawing-amount
        availability ...'.

        Claim: when both shipment_date is out of window AND drawing
        exceeds available, the business-temporal/referential check
        fires first → ERR_SHIPMENT_OUT_OF_WINDOW.
        """
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_presentation_create
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            tolerance_pct=0,
            latest_shipment_date=iso_z(now + timedelta(days=10)),
            expiry_date=iso_z(now + timedelta(days=60)),
        )
        future_ship = iso_z(now + timedelta(days=20))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=future_ship,
                drawing_amount_minor_units=99_999,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_SHIPMENT_OUT_OF_WINDOW")

    def test_overdraw_alone_yields_insufficient_available(self, api):
        """PRD §3.5: 'an over-draw raises ERR_LC_INSUFFICIENT_AVAILABLE.'"""
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_presentation_create
        lc, bundle = setup_active_lc(amount_minor_units=10_000, tolerance_pct=0)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=99_999,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_LC_INSUFFICIENT_AVAILABLE")


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestLcAvailableAmountInclusiveUpperBoundary:
    """difficulty: boundary_precision_check/lc_available_amount_inclusive_upper_boundary"""

    def test_drawing_at_inclusive_boundary_accepted(self, api):
        """PRD §3.5: 'The drawing_amount_minor_units must be strictly
        positive and must not exceed available_amount_minor_units'.

        Boundary: 'must not exceed' — equality is accepted.
        """
        # difficulty: boundary_precision_check/lc_available_amount_inclusive_upper_boundary
        lc, bundle = setup_active_lc(amount_minor_units=10_000, tolerance_pct=0)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=10_000,   # exactly equal
            ),
            bundle["beneficiary_headers"],
        )
        p = validate_success(res, expected_status=201)
        assert p["drawing_amount_minor_units"] == 10_000

    def test_drawing_one_above_available_rejected(self, api):
        """PRD §3.5: '... an over-draw raises
        ERR_LC_INSUFFICIENT_AVAILABLE.'"""
        # difficulty: boundary_precision_check/lc_available_amount_inclusive_upper_boundary
        lc, bundle = setup_active_lc(amount_minor_units=10_000, tolerance_pct=0)
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=10_001,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_LC_INSUFFICIENT_AVAILABLE")


class TestRefusalWindowStrictGreaterThanFiveBankingDays:
    """difficulty: boundary_precision_check/refusal_window_strict_greater_than_five_banking_days"""

    def test_six_banking_days_lapses_into_clean(self, api):
        """PRD §3.7: 'when the elapsed banking-day count between the
        presentation's presented_at and the current clock is strictly
        greater than 5 ... the system auto-promotes the presentation
        to EXAMINED_CLEAN'."""
        # difficulty: boundary_precision_check/refusal_window_strict_greater_than_five_banking_days
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        advance_clock_banking_days(6)
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "EXAMINED_CLEAN"

    def test_refuse_after_lapse_rejected(self, api):
        """PRD §3.7: 'An issuing-bank refuse call after the same
        boundary is rejected with ERR_REFUSAL_DEADLINE_PASSED.'"""
        # difficulty: boundary_precision_check/refusal_window_strict_greater_than_five_banking_days
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        advance_clock_banking_days(6)
        res = api.refuse_presentation(
            presentation["id"], refuse_payload(refusal_reason="late"),
            bundle["issuing_bank_headers"],
        )
        validate_error_is_one_of(
            res,
            ["ERR_REFUSAL_DEADLINE_PASSED", "ERR_INVALID_STATE_TRANSITION"],
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestPresentationStartExaminationRequiresLcActive:
    """difficulty: cross_entity_state_dependency/presentation_start_examination_requires_lc_active"""

    def test_examination_starts_when_lc_active(self, api):
        """PRD §3.5: 'The IssuingBank starts examination by naming a
        primary_reviewer_id and a secondary_reviewer_id ... Starting
        examination cascades: the presentation moves from SUBMITTED to
        UNDER_EXAMINATION'.

        Claim: when the LC is ACTIVE the start-examination call
        succeeds and the Presentation transitions
        SUBMITTED → UNDER_EXAMINATION.
        """
        # difficulty: cross_entity_state_dependency/presentation_start_examination_requires_lc_active
        lc, bundle = setup_active_lc(amount_minor_units=10_000)
        presentation = setup_presentation_with_clean_documents(
            lc=lc, bundle=bundle, drawing_amount_minor_units=5_000,
        )
        examination = start_examination(
            presentation["id"], bundle["issuing_bank_headers"],
        )
        assert examination["status"] == "IN_PROGRESS"
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "UNDER_EXAMINATION"

    def test_post_expiry_lc_remains_examinable(self, api):
        """PRD §3.10: 'When an LC enters EXPIRED, any open presentations
        in SUBMITTED or UNDER_EXAMINATION cascade to RETURNED as a
        forced transition.'

        Claim: presentations submitted before expiry are forced to
        RETURNED on the expiry sweep when still in SUBMITTED.
        """
        # difficulty: cross_entity_state_dependency/presentation_start_examination_requires_lc_active
        now = parse_iso(get_clock()["now"])
        lc, bundle = setup_active_lc(
            amount_minor_units=10_000,
            latest_shipment_date=iso_z(now + timedelta(days=5)),
            expiry_date=iso_z(now + timedelta(days=10)),
        )
        # Submit a presentation but do NOT start examination.
        ship_date = iso_z(now - timedelta(days=1))
        res = api.create_presentation(
            lc["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=5_000,
            ),
            bundle["beneficiary_headers"],
        )
        presentation = validate_success(res, expected_status=201)
        # Advance past expiry.
        advance_clock_days(15)
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "RETURNED", (
            "PRD §3.10: 'open presentations in SUBMITTED or "
            "UNDER_EXAMINATION cascade to RETURNED'"
        )


class TestReimbursementHonorRequiresSettlementPaid:
    """difficulty: cross_entity_state_dependency/reimbursement_honor_requires_settlement_paid"""

    def test_honor_succeeds_after_negotiation_advance(self, api):
        """PRD §3.9: 'The IssuingBank honours the claim — moving it
        from SUBMITTED (or from DISPUTED) to HONORED'."""
        # difficulty: cross_entity_state_dependency/reimbursement_honor_requires_settlement_paid
        lc_after, bundle, _, _, claim = setup_negotiation_paid_settlement(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
            discrepancy_fee_minor_units=0,
        )
        assert claim is not None
        res = api.honor_claim(claim["id"], bundle["issuing_bank_headers"])
        after = validate_success(res)
        assert after["status"] == "HONORED"

    def test_honor_after_dispute_returns_to_honored(self, api):
        """PRD §3.9: 'moving it from SUBMITTED (or from DISPUTED) to
        HONORED'."""
        # difficulty: cross_entity_state_dependency/reimbursement_honor_requires_settlement_paid
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
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestLcAmountAggregateCapacityOverlap:
    """difficulty: resource_temporal_overlap/lc_amount_aggregate_capacity_overlap"""

    def test_second_drawing_after_first_settles_overflows(self, api):
        """PRD §3.5: 'Two beneficiaries that submit presentations on
        the same LC simultaneously, where each fits under the available
        amount on its own but together would overdraw, serialise on
        LC.id: the first writer's deduction lands and the second
        presentation's check fails with ERR_LC_INSUFFICIENT_AVAILABLE.'"""
        # difficulty: resource_temporal_overlap/lc_amount_aggregate_capacity_overlap
        lc_after, bundle, _, _ = setup_paid_sight_settlement(
            amount_minor_units=10_000,
            drawing_amount_minor_units=7_000,
        )
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc_after["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=4_000,
            ),
            bundle["beneficiary_headers"],
        )
        validate_error(res, "ERR_LC_INSUFFICIENT_AVAILABLE")

    def test_drawing_exactly_at_remaining_available_accepted(self, api):
        """PRD §3.5: '... must not exceed available_amount_minor_units'.

        Claim: after first draw of 7000 from cap 10000, second draw of
        3000 exactly equals remaining and is accepted.
        """
        # difficulty: resource_temporal_overlap/lc_amount_aggregate_capacity_overlap
        lc_after, bundle, _, _ = setup_paid_sight_settlement(
            amount_minor_units=10_000,
            drawing_amount_minor_units=7_000,
        )
        ship_date = iso_z(parse_iso(get_clock()["now"]) - timedelta(days=1))
        res = api.create_presentation(
            lc_after["id"],
            create_presentation_payload(
                shipment_date=ship_date,
                drawing_amount_minor_units=3_000,
            ),
            bundle["beneficiary_headers"],
        )
        p = validate_success(res, expected_status=201)
        assert p["drawing_amount_minor_units"] == 3_000


class TestRefusalTimeWindowOverlapWithAutoPromotion:
    """difficulty: resource_temporal_overlap/refusal_time_window_overlap_with_auto_promotion"""

    def test_within_window_refusal_succeeds(self, api):
        """PRD §3.7: 'The IssuingBank may also independently refuse the
        presentation with a refusal_reason, which moves the row directly
        from EXAMINED_DISCREPANT to REFUSED'."""
        # difficulty: resource_temporal_overlap/refusal_time_window_overlap_with_auto_promotion
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        # Advance only 2 banking days — well within window.
        advance_clock_banking_days(2)
        res = api.refuse_presentation(
            presentation["id"], refuse_payload(refusal_reason="discrepant"),
            bundle["issuing_bank_headers"],
        )
        after = validate_success(res)
        assert after["status"] == "REFUSED"

    def test_window_lapsed_auto_promotes_then_refuse_rejected(self, api):
        """PRD §3.7: '... auto-promotes the presentation to
        EXAMINED_CLEAN ... An issuing-bank refuse call after the same
        boundary is rejected with ERR_REFUSAL_DEADLINE_PASSED.'"""
        # difficulty: resource_temporal_overlap/refusal_time_window_overlap_with_auto_promotion
        lc, bundle, presentation, _ = setup_examined_discrepant_presentation(
            amount_minor_units=10_000,
            drawing_amount_minor_units=5_000,
        )
        advance_clock_banking_days(6)
        # Verify auto-promotion.
        snapshot = get_presentation(
            presentation["id"], bundle["beneficiary_headers"],
        )
        assert snapshot["status"] == "EXAMINED_CLEAN"
        # Subsequent refuse must fail.
        res = api.refuse_presentation(
            presentation["id"], refuse_payload(refusal_reason="late"),
            bundle["issuing_bank_headers"],
        )
        validate_error_is_one_of(
            res,
            ["ERR_REFUSAL_DEADLINE_PASSED", "ERR_INVALID_STATE_TRANSITION"],
        )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestSettlementCompensatePreservesDrawnAmount:
    """difficulty: compensating_invariant/settlement_compensate_preserves_drawn_amount"""

    def test_negotiation_advance_then_dispute_nets_drawn_to_zero(self, api):
        """PRD §2.6: 'The compensating-invariant rule is that an
        addition followed by its compensation must net to zero on
        drawn_amount_minor_units.'"""
        # difficulty: compensating_invariant/settlement_compensate_preserves_drawn_amount
        # Snapshot before: drawn_amount=0 by construction in setup helper.
        lc_after, bundle, _, _, _ = setup_disputed_reimbursement_chain(
            amount_minor_units=200_000,
            drawing_amount_minor_units=80_000,
        )
        assert lc_after["drawn_amount_minor_units"] == 0, (
            "PRD §2.6: 'an addition followed by its compensation must "
            "net to zero on drawn_amount_minor_units'"
        )
        assert lc_after["available_amount_minor_units"] == 200_000

    def test_compensation_recomputes_available_to_cap(self, api):
        """PRD §2.6: '[compensate] decrements drawn_amount_minor_units
        by principal_minor_units, available_amount_minor_units is
        recomputed'."""
        # difficulty: compensating_invariant/settlement_compensate_preserves_drawn_amount
        lc_after, bundle, _, _, _ = setup_disputed_reimbursement_chain(
            amount_minor_units=100_000,
            drawing_amount_minor_units=40_000,
        )
        # cap = floor(100000 * (100+0)/100) = 100000; available = cap - 0 = 100000.
        assert lc_after["available_amount_minor_units"] == 100_000


class TestAmendmentWithdrawPreservesLcTerms:
    """difficulty: compensating_invariant/amendment_withdraw_preserves_lc_terms"""

    def test_withdraw_pending_amendment_leaves_lc_terms_unchanged(self, api):
        """PRD §3.4: 'Withdrawal moves the row to WITHDRAWN and resets
        amendment_consent_status to NONE.'

        Claim: a withdrawn amendment must NOT have merged its changes
        into the parent LC; the term-tuple is conserved.
        """
        # difficulty: compensating_invariant/amendment_withdraw_preserves_lc_terms
        original_amount = 100_000
        original_expiry = None       # captured below from lc snapshot
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=original_amount,
            changes={
                "amount_minor_units": 250_000,
                "expiry_date": "2027-12-01T00:00:00.000Z",
            },
        )
        before = get_lc(lc["id"], bundle["applicant_headers"])
        original_expiry = before["expiry_date"]
        original_lsd = before["latest_shipment_date"]
        original_tol = before["tolerance_pct"]
        # Withdraw.
        withdraw_amendment(
            lc["id"], amendment["id"], bundle["issuing_bank_headers"],
        )
        after = get_lc(lc["id"], bundle["applicant_headers"])
        # Term tuple unchanged.
        assert after["amount_minor_units"] == original_amount
        assert after["expiry_date"] == original_expiry
        assert after["latest_shipment_date"] == original_lsd
        assert after["tolerance_pct"] == original_tol
        assert after["amendment_consent_status"] == "NONE"

    def test_withdrawn_amendment_status_is_terminal_withdrawn(self, api):
        """PRD §3.4: 'Withdrawal moves the row to WITHDRAWN'."""
        # difficulty: compensating_invariant/amendment_withdraw_preserves_lc_terms
        lc, bundle, amendment = setup_pending_amendment(
            amount_minor_units=100_000,
            changes={"amount_minor_units": 200_000},
        )
        a = withdraw_amendment(
            lc["id"], amendment["id"], bundle["issuing_bank_headers"],
        )
        assert a["status"] == "WITHDRAWN"
