"""Queue A (depth) — the budget ledger's two variance views on identical data.

An open PO line (40 units x 15000c = 600000c, cube 10, nothing received, no
freight sealed yet) sits against a FURNITURE budget line of 8000000c; the
commitment view and the final view must diverge by exactly the open commitment.
"""
from test_helpers import (
    api_client, validate_success, validate_paginated,
    run_pipeline, assert_budget_line, assert_project_rollup_invariants,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]


def _setup_open_commitment():
    return run_pipeline(
        name="P-DV1", total_budget_cents=10_000_000,
        unallocated_contingency_cents=100_000, budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
            "spec_overrides": {"required_lead_days": 21},
        }],
        attach=False, seal=False, depart=False,
    )


def test_commitment_view_counts_open_po_commitments(api):
    """PRD §2.10: "A line's `committed_cents` is the sum, over every PO line whose
    spec's category equals the budget line's category, whose own status is not
    `CANCELLED`, and whose purchase order's `fulfillment_status` is one of `ISSUED`,
    `ACKNOWLEDGED`, `READY_TO_SHIP`, or `CONSOLIDATED`, of that PO line's
    `extended_cents` plus its `freight_alloc_provisional_cents`."
    PRD §2.10: "`variance_commitment_cents` is `budgeted_cents` minus
    `committed_cents` minus `actual_cents`: the forward-looking exposure view used
    by the budget gate at PO-line creation."
    The PO is ISSUED with extended 600000c and no freight sealed, so committed is
    600000c and the commitment variance is 8000000 - 600000 - 0 = 7400000c.

    Design: Difficulty/dual_variant_calc/budget_variance_commitment_vs_final_view
    """
    scenario = _setup_open_commitment()
    budget_line = scenario["budget_line"]

    assert budget_line["committed_cents"] == 600000, (
        f"ISSUED PO line 40 x 15000c must enter committed; got "
        f"{budget_line['committed_cents']}"
    )
    assert budget_line["actual_cents"] == 0
    assert budget_line["variance_commitment_cents"] == 7400000
    assert_budget_line(budget_line)


def test_final_view_ignores_open_commitments(api):
    """PRD §2.10: "`variance_final_cents` is `budgeted_cents` minus `actual_cents`:
    the reconciled view, which ignores open commitments entirely. Two identical
    datasets therefore show different variances whenever any purchase order is
    still open."
    PRD §2.10: "At the project level, `committed_cents` is the sum of the budget
    lines' `committed_cents`, and `actual_spend_cents` is the sum of their
    `actual_cents`."
    With nothing received, the final variance is the full 8000000c while the
    commitment variance is 7400000c on the same underlying data.

    Design: Difficulty/dual_variant_calc/budget_variance_commitment_vs_final_view
    """
    scenario = _setup_open_commitment()
    budget_line = scenario["budget_line"]

    assert budget_line["actual_cents"] == 0
    assert budget_line["variance_final_cents"] == 8000000
    assert budget_line["variance_commitment_cents"] == 7400000
    assert (
        budget_line["variance_commitment_cents"]
        != budget_line["variance_final_cents"]
    ), "the two variance views must diverge while any PO is still open"

    project = scenario["project"]
    lines, _meta = validate_paginated(
        api_client.list_project_budget_lines(project["id"], PA)
    )
    assert project["committed_cents"] == 600000
    assert project["actual_spend_cents"] == 0
    assert_project_rollup_invariants(project, lines)
