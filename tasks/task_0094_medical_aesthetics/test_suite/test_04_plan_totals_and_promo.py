"""Treatment-plan totals — provisional vs final, promo, and version locking.

PRD §3.3 defines two computed totals on TreatmentPlan:
  - provisional_total_cents — live-read pricing, no promo, recomputed on
    create / DRAFT edit / submit.
  - final_total_cents — snapshot pricing, applies the >=3-item 5% promo,
    locked on SUBMITTED → APPROVED.

Both compute over the SAME items array but produce different totals
when there are at least three items.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ATTENDING_PHYSICIAN_ID,
    ApiErrorId,
    PROMO_RATE_BPS,
    PROMO_THRESHOLD_ITEMS,
    TEST_USERS,
    api_client,
    approve_plan_via_attending,
    assert_treatment_plan,
    create_draft_plan,
    create_kyc_verified_customer,
    create_on_shelf_project,
    create_plan_payload,
    get_plan,
    plan_item,
    setup_approved_plan_three_items_promo,
    setup_draft_plan,
    sign_consent,
    submit_plan,
    validate_error,
    validate_success,
)


# ===========================================================================
# Provisional total — live pricing, no promo (PRD §3.3)
# ===========================================================================
class TestProvisionalTotal:

    def test_provisional_total_on_draft_no_promo_under_three_items(self, api):
        """PRD §3.3: "Per-line rounding is applied in this order —
        multiply-then-accumulate — though for pure integer cents the
        per-line rounding step has no effect. The provisional variant
        reads pricing live, so the same plan's provisional_total_cents
        may drift across edits if the underlying project pricing is
        changed by the catalog. No promotional discount is applied to
        the provisional total."

        Claim: 2 items at 100000 cents each → provisional_total_cents
        is 2 × 100000 = 200000 (no promo because items < 3).
        """
        ctx = setup_draft_plan(num_items=2, base_price_cents=100000)
        plan = ctx["plan"]
        assert_treatment_plan(plan)
        assert plan["provisional_total_cents"] == 200000, (
            f"Provisional should equal 2 × 100000 = 200000, got "
            f"{plan['provisional_total_cents']}"
        )
        # No promo at provisional, regardless of length.
        assert plan["final_total_cents"] is None, (
            "final_total_cents must remain null until APPROVED"
        )

    def test_provisional_total_for_three_items_no_promo(self, api):
        """PRD §3.3: "No promotional discount is applied to the
        provisional total."

        Claim: 3 items × 100000 → provisional == 300000, not 285000.
        """
        ctx = setup_draft_plan(num_items=3, base_price_cents=100000)
        plan = ctx["plan"]
        assert plan["provisional_total_cents"] == 300000, (
            f"Provisional with 3 items must be 3 × 100000 = 300000 "
            f"(no promo); got {plan['provisional_total_cents']}"
        )


# ===========================================================================
# Final total — locked snapshot + promo (Rule 1 instance 1)
# ===========================================================================
# difficulty: dual_variant_calc/plan_total_provisional_vs_final_on_treatment_plan
class TestFinalTotalPromo:
    """PRD §3.3: "The final_total_cents calculation differs from the
    provisional in three concrete ways: it locks pricing to the
    snapshot taken at approval time (rather than reading live), it
    applies a promotional discount if the plan has at least 3 items,
    and its rounding order is per-line discount first then sum (no
    final rounding step over the sum)."
    """

    def test_final_total_three_items_applies_five_percent_promo(self, api):
        """PRD §3.3: "The promotional rate in basis points is 500 when
        the number of items in the plan is at least 3 and 0 otherwise.
        The line discount is the line gross multiplied by the
        promotional rate and then divided by 10000 using integer
        floor division; this floor step is the locked rounding
        semantics."

        Claim: 3 items × 100000 → each line discount = floor(100000 ×
        500 / 10000) = 5000; line_net = 95000; sum = 3 × 95000 = 285000.

        # difficulty: dual_variant_calc/plan_total_provisional_vs_final_on_treatment_plan
        """
        ctx = setup_approved_plan_three_items_promo(base_price_cents=100000)
        plan = ctx["plan"]
        assert plan["status"] == "APPROVED"
        # Provisional was 3 × 100000 = 300000 (no promo at provisional).
        assert plan["provisional_total_cents"] == 300000, (
            f"Provisional must remain 300000; got "
            f"{plan['provisional_total_cents']}"
        )
        # Final applies the 5% promo because items.length >= 3.
        assert plan["final_total_cents"] == 285000, (
            f"Final with 3 items × 100000 and 5% promo must equal "
            f"3 × (100000 − 5000) = 285000; got "
            f"{plan['final_total_cents']}"
        )

    def test_final_differs_from_provisional_at_promo_threshold(self, api):
        """PRD §3.3: "Because the snapshot pricing may differ from the
        live pricing read at submission, and because the promotion
        only applies at finalization, the provisional and final totals
        can diverge for the same item list."

        Claim: identical items list with three entries yields
        provisional != final on the SAME plan.

        # difficulty: dual_variant_calc/plan_total_provisional_vs_final_on_treatment_plan
        """
        ctx = setup_approved_plan_three_items_promo(base_price_cents=100000)
        plan = ctx["plan"]
        assert plan["provisional_total_cents"] != plan["final_total_cents"], (
            "On 3-item plan with promo, provisional and final must "
            "differ"
        )

    def test_locked_project_versions_non_null_after_approval(self, api):
        """PRD §3.3: "the snapshot map locked_project_versions is of
        the shape {project_id: Project.version} over every included
        project, capturing the project rows' current OCC versions at
        the moment of approval."

        Claim: locked_project_versions is a non-null map keyed by each
        included item's project_id after APPROVED.

        # difficulty: dual_variant_calc/plan_total_provisional_vs_final_on_treatment_plan
        """
        ctx = setup_approved_plan_three_items_promo()
        plan = ctx["plan"]
        snapshot = plan["locked_project_versions"]
        assert snapshot is not None, (
            "PRD §3.3: locked_project_versions must be snapshotted on "
            "approval"
        )
        assert isinstance(snapshot, dict)
        seen_project_ids = {p["id"] for p in ctx["projects"]}
        for pid in seen_project_ids:
            assert pid in snapshot, (
                f"snapshot must contain project_id {pid}"
            )
            assert isinstance(snapshot[pid], int)


# ===========================================================================
# Final total — under-threshold promo NOT applied
# ===========================================================================
class TestFinalTotalNoPromoBelowThreshold:

    def test_final_total_with_two_items_no_promo(self, api):
        """PRD §3.3: "The promotional rate in basis points is 500 when
        the number of items in the plan is at least 3 and 0 otherwise."

        Claim: 2 items × 100000 → final_total_cents = 200000 (no
        promo because items < 3).
        """
        # Use the simple-plan helper with two items.
        from test_helpers import setup_approved_plan_simple
        ctx = setup_approved_plan_simple(
            num_items=2, base_price_cents=100000,
        )
        plan = ctx["plan"]
        assert plan["status"] == "APPROVED"
        assert plan["final_total_cents"] == 200000, (
            f"Two items × 100000 with no promo = 200000; got "
            f"{plan['final_total_cents']}"
        )
