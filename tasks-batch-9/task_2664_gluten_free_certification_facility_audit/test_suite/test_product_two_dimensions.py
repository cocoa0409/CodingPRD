"""A product's formula dimension and label dimension are separate state machines:
a supplier cascade moves one of them and a label decision moves the other.
"""

from test_helpers import (
    BlockedReason,
    Decision,
    IngredientSpec,
    LabelRejectionReason,
    MarkTier,
    RiskClass,
    make_reviewer_headers,
    read_ingredient,
    read_product,
    read_supplier,
    setup_certification_ready_product,
    suspend_supplier,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"

SOLE_LINE = IngredientSpec(
    name="Brown Rice Flour",
    risk_class=RiskClass.INHERENTLY_GF,
    inclusion_pct=40,
    doc_issued_on="2026-07-01T00:00:00Z",
    doc_expires_on="2028-07-01T00:00:00Z",
)


def _planned_product_whose_supplier_then_falls(api):
    """A single-line product with a cleared formula, an active plan and an approved
    STANDARD label, never certified, whose only supplier is then suspended.

    The suspension cascade reaches the ingredient and the formula but stops short
    of the label, because no certificate ever moved.
    """
    context = setup_certification_ready_product(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SOLE_LINE,),
        run_audit=False,
    )
    suspend_supplier(api, context.supplier_id)
    return context


def test_a_supplier_suspension_blocks_the_formula_and_leaves_the_label_approved(api):
    """The cascade blocks the ingredient and the formula, but `label_status` is
    still `APPROVED` and the granted tier still `STANDARD`.

    PRD: "The two dimensions advance through separate operations and separate
    cascades; neither one reads or writes the other."
    PRD: "Only certificate movement ever writes `FROZEN`."

    Design: Difficulty/non_linear_state_machine/product_formula_and_label_dimensions_move_independently
    """
    context = _planned_product_whose_supplier_then_falls(api)

    product = read_product(api, context.product_id)
    assert product["formula_status"] == "BLOCKED"
    assert product["blocked_ingredient_count"] == 1
    assert product["label_status"] == "APPROVED"
    assert product["mark_tier_granted"] == MarkTier.STANDARD

    ingredient = read_ingredient(api, context.ingredient_id)
    assert ingredient["status"] == "BLOCKED"
    assert ingredient["blocked_reason"] == BlockedReason.SUPPLIER_SUSPENDED
    assert read_supplier(api, context.supplier_id)["status"] == "SUSPENDED"


def test_a_label_rejection_answers_two_hundred_and_resets_only_the_label_fields(api):
    """Rejecting the label of an already-blocked product succeeds, sets
    `label_status` to `REJECTED` and resets the granted tier to `NONE`.

    PRD: "A rejection must carry a `rejection_reason`, which is stored as
    `label_rejection_reason` and is one of `MARK_PLACEMENT_INVALID`,
    `UNSUPPORTED_CLAIM`, `MISSING_CERT_NUMBER` or `TIER_MISMATCH`; on rejection,
    whether the label was previously `NOT_SUBMITTED` or `APPROVED`, `label_status`
    becomes `REJECTED` and `mark_tier_granted` is reset to `NONE`, and
    `formula_status` is untouched."

    Design: Difficulty/non_linear_state_machine/product_formula_and_label_dimensions_move_independently
    """
    context = _planned_product_whose_supplier_then_falls(api)
    version_before = read_product(api, context.product_id)["version"]

    response = api.review_label(
        context.product_id,
        make_reviewer_headers("rev-2"),
        decision=Decision.REJECT,
        rejection_reason=LabelRejectionReason.MARK_PLACEMENT_INVALID,
    )
    assert response.status_code == 200, response.text
    reviewed = response.json()["data"]

    assert reviewed["label_status"] == "REJECTED"
    assert reviewed["mark_tier_granted"] == "NONE"
    assert reviewed["label_rejection_reason"] == LabelRejectionReason.MARK_PLACEMENT_INVALID
    assert reviewed["label_reviewed_by_user_id"] == "rev-2"
    assert reviewed["version"] == version_before + 1

    assert reviewed["formula_status"] == "BLOCKED"
    assert reviewed["blocked_ingredient_count"] == 1


def test_the_testing_plan_survives_both_dimension_moves_intact(api):
    """Neither the supplier cascade nor the label rejection recomputes the plan, so
    the 10 ppm threshold and its 2 lots at 182 days still stand.

    PRD: "Rejecting a formula leaves an approved label approved, and rejecting a
    label leaves a cleared formula cleared."
    PRD: "Activation computes `threshold_ppm`, then `sampling_lots_per_year` and
    `sampling_exclusion_days` from it, sets `testing_plan_status` to `ACTIVE`,
    increases `testing_plan_revision` by 1 — so the counter records how many plans
    this product has had, each superseding the last — and increases the product's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/product_formula_and_label_dimensions_move_independently
    """
    context = _planned_product_whose_supplier_then_falls(api)

    api.review_label(
        context.product_id,
        make_reviewer_headers("rev-2"),
        decision=Decision.REJECT,
        rejection_reason=LabelRejectionReason.MARK_PLACEMENT_INVALID,
    )

    product = read_product(api, context.product_id)
    assert product["threshold_ppm"] == 10
    assert product["sampling_lots_per_year"] == 2
    assert product["sampling_exclusion_days"] == 182
    assert product["testing_plan_status"] == "ACTIVE"
    assert product["testing_plan_revision"] == 1
    assert product["linked_ingredient_count"] == 1
