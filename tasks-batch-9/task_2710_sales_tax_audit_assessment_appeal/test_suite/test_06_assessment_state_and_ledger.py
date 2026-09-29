"""The notice axis, the collection axis and the ledger rows that move the balance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abate_penalty,
    api_client,
    approve_arrangement,
    list_adjustments,
    post_payment_adjustment,
    project_sample,
    read_assessment,
    read_audit,
    request_installment_plan,
    reverse_adjustment,
    setup_draft_assessment,
    setup_issued_assessment,
    stale_the_findings,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["audit_supervisor_headers"]

SCOPE_START = "2026-01-01"
PRICE_FOR_4763_CENTS = 76_208
PRICE_FOR_4762_CENTS = 76_192
EXTRA_PRICE_FOR_2500_CENTS = 40_000


def _purchase(price_cents):
    return {
        "invoice_date": SCOPE_START,
        "purchase_price_cents": price_cents,
        "asset_class": "CONSUMABLE",
    }


def _issued_on(price_cents):
    return setup_issued_assessment(purchase_specs=[_purchase(price_cents)])


def test_approving_a_plan_moves_only_the_collection_axis():
    """The notice stays issued while the money is rearranged underneath it.

    PRD 3.9: "Approval sets `approved_at`, moves the arrangement from `REQUESTED` to
    `APPROVED`, and moves the assessment's `collection_status` to `ARRANGED` — from
    `DUE` or from `REFERRED` alike — while leaving the notice axis exactly where it
    was."
    PRD 3.6: "It then does two things on other axes: it kicks the collection axis
    once, moving `collection_status` from `NOT_DUE` to `DUE`, and it moves the audit
    from `REVIEW_COMPLETE` to `ASSESSED`."

    Design: Difficulty/non_linear_state_machine/assessment_status_and_collection_axes_move_independently
    """
    ctx = _issued_on(PRICE_FOR_4763_CENTS)
    assessment = ctx["assessment"]
    assert assessment["status"] == "ISSUED"
    assert assessment["collection_status"] == "DUE"
    assert assessment["total_due_cents"] == 5_001
    assert read_audit(ctx["audit"]["id"])["status"] == "ASSESSED"

    plan = request_installment_plan(assessment["id"], 5_001, 1)
    assert plan["scheduled_total_cents"] == 5_001
    approved = approve_arrangement(plan["id"])
    assert approved["status"] == "APPROVED"

    after = read_assessment(assessment["id"])
    assert after["status"] == "ISSUED"
    assert after["collection_status"] == "ARRANGED"


def test_abating_the_penalty_moves_the_money_and_neither_axis():
    """Relief lands in the ledger, leaving both axes exactly where they stood.

    PRD 3.7: "The abated amount is `penalty_cents` multiplied by `abatement_pct`,
    divided by 100 and rounded half up, and it is computed against the **original**
    `penalty_cents` stored on the assessment rather than against any penalty net of
    an earlier abatement."
    PRD 3.7: "Abatement posts a `SYSTEM` adjustment of kind `PENALTY_ABATEMENT`
    carrying that amount, the supplied `abatement_factors` and the computed
    `abatement_pct`, which raises `total_abated_cents` and `total_adjustments_cents`
    and lowers `balance_due_cents`."

    Design: Difficulty/non_linear_state_machine/assessment_status_and_collection_axes_move_independently
    """
    ctx = _issued_on(PRICE_FOR_4763_CENTS)
    assessment = ctx["assessment"]
    assert assessment["penalty_cents"] == 238
    plan = request_installment_plan(assessment["id"], 5_001, 1)
    approve_arrangement(plan["id"])

    abate_penalty(assessment["id"], ["FIRST_TIME_COMPLIANT"])

    after = read_assessment(assessment["id"])
    # 40 points of relief on a 238-cent penalty, rounded half up.
    assert after["total_abated_cents"] == 95
    assert after["total_adjustments_cents"] == 95
    assert after["balance_due_cents"] == 4_906
    assert after["total_due_cents"] == 5_001
    assert after["status"] == "ISSUED"
    assert after["collection_status"] == "ARRANGED"


def test_a_posted_payment_row_clears_the_balance_and_satisfies_the_liability():
    """The ledger credit, not an edit of the assessed total, drives the balance to zero.

    PRD 3.7: "A successful posting sets `status` to `POSTED` and `source` to
    `MANUAL`, re-derives the assessment's `total_adjustments_cents` and
    `balance_due_cents`, and, when the balance reaches exactly 0, moves the
    collection axis to `SATISFIED`."
    PRD 3.7: "`amount_paid_cents` is a deliberately separate aggregate that
    accumulates only the cash recorded through an arrangement's payments, not the
    ledger's `PAYMENT` rows; a manually posted `PAYMENT` adjustment flows into
    `total_adjustments_cents` instead."

    Design: Difficulty/compensating_invariant/adjustment_reversal_restores_the_balance_identity
    """
    ctx = _issued_on(PRICE_FOR_4762_CENTS)
    assessment = ctx["assessment"]
    assert assessment["total_due_cents"] == 4_762
    assert assessment["balance_due_cents"] == 4_762

    row = post_payment_adjustment(assessment["id"], assessment["version"], 4_762)
    assert row["kind"] == "PAYMENT"
    assert row["source"] == "MANUAL"
    assert row["status"] == "POSTED"

    after = read_assessment(assessment["id"])
    assert after["total_adjustments_cents"] == 4_762
    assert after["amount_paid_cents"] == 0
    assert after["balance_due_cents"] == 0
    assert after["collection_status"] == "SATISFIED"
    assert after["status"] == "ISSUED"


def test_reversing_the_payment_restores_the_balance_it_had_removed():
    """The row survives as history and the conserved-money identity still holds.

    PRD 3.7: "Reversal then re-derives `total_adjustments_cents`,
    `total_abated_cents` and `balance_due_cents` so that the conserved-money
    invariant still holds exactly — reversing a credit restores the balance it had
    removed, and reversing a `COLLECTION_FEE` removes the charge it had added."
    PRD 3.7: "A `SATISFIED` assessment whose balance becomes positive again as a
    result returns to `collection_status` `DUE`."
    PRD 3.7: "The conserved-money invariant closes the system: after every mutation,
    `balance_due_cents` plus `total_adjustments_cents` plus `amount_paid_cents`
    equals `total_due_cents`."

    Design: Difficulty/compensating_invariant/adjustment_reversal_restores_the_balance_identity
    """
    ctx = _issued_on(PRICE_FOR_4762_CENTS)
    assessment = ctx["assessment"]
    row = post_payment_adjustment(assessment["id"], assessment["version"], 4_762)

    reversed_row = reverse_adjustment(row["id"])
    assert reversed_row["status"] == "REVERSED"

    after = read_assessment(assessment["id"])
    assert after["total_adjustments_cents"] == 0
    assert after["amount_paid_cents"] == 0
    assert after["balance_due_cents"] == 4_762
    assert after["total_due_cents"] == 4_762
    assert after["collection_status"] == "DUE"
    assert after["status"] == "ISSUED"
    assert (
        after["balance_due_cents"]
        + after["total_adjustments_cents"]
        + after["amount_paid_cents"]
        == after["total_due_cents"]
    )
    # The reversed row is still on file, it simply drops out of the sum.
    rows = list_adjustments(assessment_id=assessment["id"])
    assert [existing["status"] for existing in rows] == ["REVERSED"]


def _stale_draft_with_a_new_finding():
    """A DRAFT_STALE notice whose audit has grown a 2,500-cent finding since drafting."""
    ctx = setup_draft_assessment(purchase_specs=[_purchase(PRICE_FOR_4763_CENTS)])
    stale_the_findings(ctx, purchase_price_cents=EXTRA_PRICE_FOR_2500_CENTS)
    return ctx


def test_a_notice_cannot_be_recomputed_while_the_audit_is_still_stale():
    """The audit must catch up first, so the frozen amounts stay frozen.

    PRD 3.6: "An `AuditSupervisor` clears the flag by recomputing, which is accepted
    only from `DRAFT_STALE` and only when the audit's `projection_status` has
    returned to `CURRENT` — a stale audit yields `ERR_PROJECTION_STALE`, and
    recomputing an assessment that is already `DRAFT` is refused with
    `ERR_INVALID_STATE`."
    PRD 3.6: "In `DRAFT_STALE` the stored amounts are frozen exactly as they were
    and issuance is blocked."

    Design: Difficulty/cross_entity_state_dependency/recompute_depends_on_the_audits_projection_status
    """
    ctx = _stale_draft_with_a_new_finding()
    assert ctx["assessment"]["status"] == "DRAFT_STALE"
    assert ctx["audit"]["projection_status"] == "STALE"

    response = api_client.recompute_assessment(ctx["assessment"]["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_PROJECTION_STALE.value, 409)

    frozen = read_assessment(ctx["assessment"]["id"])
    assert frozen["status"] == "DRAFT_STALE"
    assert frozen["tax_deficiency_cents"] == 4_763


def test_recomputing_after_the_projection_is_current_picks_up_the_new_finding():
    """Once the audit is current again the rollup runs over the larger deficiency.

    PRD 3.6: "A recompute re-runs the whole five-step rollup and overwrites
    `tax_deficiency_cents`, `penalty_rate_bp`, `penalty_cents`, `interest_days`,
    `interest_cents`, `provisional_total_due_cents`, `penalty_waived_small_balance`,
    `total_due_cents` and `balance_due_cents`, then returns the assessment to
    `DRAFT`."

    Design: Difficulty/cross_entity_state_dependency/recompute_depends_on_the_audits_projection_status
    """
    ctx = _stale_draft_with_a_new_finding()

    audit = project_sample(ctx["audit"]["id"])
    assert audit["projection_status"] == "CURRENT"
    assert audit["use_tax_deficiency_cents"] == 7_263

    response = api_client.recompute_assessment(ctx["assessment"]["id"], SUPERVISOR)
    recomputed = validate_success(response, 200)

    assert recomputed["status"] == "DRAFT"
    assert recomputed["tax_deficiency_cents"] == 7_263
    assert recomputed["penalty_rate_bp"] == 500
    assert recomputed["penalty_cents"] == 363
    assert recomputed["interest_days"] == 0
    assert recomputed["penalty_waived_small_balance"] is False
    assert recomputed["total_due_cents"] == 7_626
    assert recomputed["balance_due_cents"] == 7_626
