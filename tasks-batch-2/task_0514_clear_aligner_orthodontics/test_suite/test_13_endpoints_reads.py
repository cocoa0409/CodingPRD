"""Endpoint read corner cases: computed ledger fields and self-referential
filter reverse-reachability (PRD §3.5, §3.8, §3.9)."""
from test_helpers import (
    validate_success, validate_paginated,
    setup_case_active, setup_refinement_requested, list_steps,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]
MFG = TEST_USERS["manufacturing_headers"]


def test_get_case_returns_ledger_fields_after_activation(api):
    """PRD §3.7: "posts the down payment by adding `down_payment_cents` to the
    case's `amount_collected_cents`".
    PRD §3.5: "the system generates a number of `AlignerStep` rows equal to the
    plan's `proposed_step_count` ... and sets the case's `planned_step_count` to
    that count."

    After activation with a 300000 down payment and a 10-step plan, GET /cases/{id}
    reflects amount_collected_cents=300000 and planned_step_count=10.

    Design: Corner/endpoints/get_case_summary_returns_ledger_fields
    """
    ctx = setup_case_active(proposed_step_count=10, list_price_cents=375000,
                            down_payment_cents=300000)
    # list 375000, 10 steps LIGHT 0.80 -> 300000 contracted; full down payment.
    case = validate_success(api.get_case(ctx["case"]["id"], BILLING), 200)
    assert case["amount_collected_cents"] == 300000, case["amount_collected_cents"]
    assert case["planned_step_count"] == 10, case["planned_step_count"]


def test_list_aligner_steps_filtered_by_supersedes_after_refinement(api):
    """PRD §3.9: "the system generates `additional_step_count` new `AlignerStep`
    rows in `PLANNED`, each with its `supersedes_step_id` set to the matching
    original step it replaces".
    PRD §4 (endpoint): "List aligner steps, filterable by case or superseded
    step."

    After a granted refinement generates a correction step superseding step 1,
    GET /aligner-steps?supersedes_step_id={s1} returns at least that refinement
    step.

    Design: Corner/endpoints/list_steps_filtered_by_supersedes_after_refinement
    """
    ctx = setup_refinement_requested(assessment="OFF_TRACK", additional_step_count=1,
                                     proposed_step_count=10)
    steps = list_steps(ctx["case"]["id"])
    s1 = steps[0]
    validate_success(api.grant_refinement(ctx["refinement"]["id"], ctx["clin_headers"]), 200)
    data, meta = validate_paginated(
        api.list_aligner_steps(MFG, params={"supersedes_step_id": s1["id"]})
    )
    assert meta["total_count"] >= 1, meta["total_count"]
    assert all(s["supersedes_step_id"] == s1["id"] for s in data), data
