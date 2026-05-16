"""Chronological replay at finalisation: usda_reimbursement_final.

PRD §3.7: final_reimbursement_cents is computed by chronological replay
against CURRENT eligibility and allergy state, not the snapshot stored
on the SERVED row. Thus the same rows that produced provisional_total_cents
can yield a different final_reimbursement_cents when a student's tier
changed between SERVED and FINALIZED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    USDA_FREE_RATE_CENTS,
    USDA_PAID_RATE_CENTS,
    api_client,
    create_allergy_entry,
    create_meal_serving,
    create_menu_item,
    finalize_usda_claim,
    setup_three_paid_servings_then_approve_free,
    submit_and_finalize_claim,
    submit_usda_claim,
    create_usda_claim,
    validate_success,
)


# ===========================================================================
# §3.7 Provisional vs final divergence on tier change
# ===========================================================================
class TestProvisionalVsFinalDivergence:
    """PRD §3.7 + difficulty
    dual_variant_calc/usda_reimbursement_provisional_vs_final_on_claim."""

    def test_provisional_paid_then_final_free_diverge(self, api):
        """PRD §3.7: "Because the final replay reads current
        eligibility and current allergy state rather than the SERVED-
        time snapshots, final_reimbursement_cents and
        provisional_total_cents can legitimately disagree whenever a
        student's eligibility_tier changed between serving and
        finalisation (for example, an FRL approval landed mid-period)
        or whenever an allergy entry was added that intersects a
        previously-served meal's labelled allergens."

        Claim: 3 PAID servings (provisional=50 each → total 150) then
        the student is approved to FREE; on finalize the chronological
        replay re-resolves each row's tier against CURRENT student
        tier (FREE), yielding final = 3 × 480 = 1440. Provisional
        (150) and final (1440) disagree.

        # difficulty: dual_variant_calc/usda_reimbursement_provisional_vs_final_on_claim
        # difficulty: transitive_cascade/approve_application_cascades_through_eligibility_to_serving_to_claim
        # difficulty: combinatorial_formula/usda_reimbursement_final_chronological_order_pinning
        """
        ctx = setup_three_paid_servings_then_approve_free()
        # Claim covering the three serving days.
        claim = create_usda_claim(
            district=ctx["district"],
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-09-30T00:00:00.000Z",
        )
        submit_usda_claim(district=ctx["district"], claim=claim)
        finalized = finalize_usda_claim(
            district=ctx["district"], claim=claim,
        )
        # PRD §3.6: each PAID serving on a reimbursable item stamped 50
        # cents at SERVED time.
        assert finalized["provisional_total_cents"] == 150, (
            f"expected provisional 50*3=150, got "
            f"{finalized['provisional_total_cents']}"
        )
        # PRD §3.7 chronological replay: each row re-resolves to the
        # student's CURRENT tier (FREE), rate 480 each, total 1440.
        assert finalized["final_reimbursement_cents"] == 1440, (
            f"expected final 480*3=1440, got "
            f"{finalized['final_reimbursement_cents']}"
        )
        # And the two differ.
        assert (
            finalized["provisional_total_cents"]
            != finalized["final_reimbursement_cents"]
        )

    def test_serving_record_ids_ordered_by_created_at(self, api):
        """PRD §3.7: "the identifiers of every MealServingRecord whose
        status is SERVED and whose serving_date lies between the
        claim's period_start and period_end inclusive, ordered by
        created_at ascending with ties broken by record id ascending."

        Claim: serving_record_ids on the finalised claim is exactly
        the insertion order of the three servings.
        """
        ctx = setup_three_paid_servings_then_approve_free()
        claim = create_usda_claim(
            district=ctx["district"],
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-09-30T00:00:00.000Z",
        )
        submit_usda_claim(district=ctx["district"], claim=claim)
        finalized = finalize_usda_claim(
            district=ctx["district"], claim=claim,
        )
        expected_ids = [s["id"] for s in ctx["servings"]]
        assert finalized["serving_record_ids"] == expected_ids, (
            f"expected snapshot order {expected_ids}, got "
            f"{finalized['serving_record_ids']}"
        )


# ===========================================================================
# §3.7 Non-reimbursable item contributes zero
# ===========================================================================
class TestNonReimbursableInFinal:
    """PRD §3.7: "zero when the menu item's reimbursable is false"."""

    def test_non_reimbursable_contributes_zero_to_final(self, api):
        """PRD §3.7: "For each snapshot row, in the snapshot order
        (created_at ascending, ties broken by id ascending), the system
        evaluates a rate. ... [it selects] zero when the menu item's
        reimbursable is false".

        Claim: a single serving of a non-reimbursable menu item →
        final_reimbursement_cents == 0.
        """
        from test_helpers import (
            advance_clock_to,
            setup_student_with_tier,
        )
        district, parent, student, _app = setup_student_with_tier(
            target_tier="FREE",
            school_year_start="2026-08-01T00:00:00.000Z",
        )
        item = create_menu_item(
            district=district, full_price_cents=300, reimbursable=False,
        )
        advance_clock_to("2026-09-12T12:00:00.000Z")
        create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        finalized = submit_and_finalize_claim(
            district=district,
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-09-30T00:00:00.000Z",
        )
        assert finalized["final_reimbursement_cents"] == 0


# ===========================================================================
# §3.7 Allergy added between SERVED and FINALIZED overrides to 0
# ===========================================================================
class TestAllergyAddedAfterServing:
    """PRD §3.7: "After the rate is selected, the system checks whether
    the student is currently allergen-blocked against this specific
    row's menu item ... if so, the row's rate is overridden to zero."
    """

    def test_active_allergy_at_finalize_overrides_rate_to_zero(self, api):
        """PRD §3.7: "the system checks whether the student is
        currently allergen-blocked against this specific row's menu
        item — that is, whether any of the student's ACTIVE allergy
        entries has an allergen appearing in the row's
        MenuItem.contains_allergens; if so, the row's rate is
        overridden to zero."

        Claim: a FREE-tier reimbursable serving (rate 480) becomes 0
        when an ACTIVE allergy intersecting the menu item is added
        before finalisation.
        """
        from test_helpers import (
            advance_clock_to,
            setup_student_with_tier,
        )
        district, parent, student, _app = setup_student_with_tier(
            target_tier="FREE",
            school_year_start="2026-08-01T00:00:00.000Z",
        )
        # Item with no allergens at SERVED time → serving succeeds.
        item = create_menu_item(
            district=district, full_price_cents=300, reimbursable=True,
            contains_allergens=["DAIRY"],
        )
        # Student has NO allergy at SERVED time.
        advance_clock_to("2026-09-14T12:00:00.000Z")
        create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        # Add a DAIRY allergy after the serving but before finalise.
        create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="DAIRY", severity="MILD",
        )
        # Build and finalise a claim covering the serving day.
        finalized = submit_and_finalize_claim(
            district=district,
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-09-30T00:00:00.000Z",
        )
        # PRD §3.7 chronological replay: rate is overridden to 0.
        assert finalized["final_reimbursement_cents"] == 0, (
            f"expected 0 (allergen override), got "
            f"{finalized['final_reimbursement_cents']}"
        )
