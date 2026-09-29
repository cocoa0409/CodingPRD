"""Certifying the statewide first cost, and compensating the cycle ledger."""
from test_helpers import (
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_paginated,
)


def test_01_permits_are_rounded_to_whole_permits_before_the_multiplication(api):
    """"The annual permit population is first split into whole permits per
    occupancy class, and only then multiplied by that class's per-permit cost."
    Over 2,410 permits at the fixed shares of "62 percent for `R3`, 18 percent
    for `R2`, 12 percent for `B` and 8 percent for `A2`" the certified total is
    143,002,800 cents; "rounding the money instead of the permits, or leaving
    fractional permits in the multiplication, both produce a different and
    incorrect answer".

    Design: Difficulty/combinatorial_formula/statewide_cost_rollup_permit_level_rounding_order_decides_result
    """
    world = fixtures.setup_screened_proposal(api)
    fixtures.file_cost_benefit_analysis(api, world)

    fixtures.review_analysis(api, world["cost_benefit_id"])

    analysis = get_success_data(
        api.get_impact_analysis(world["cost_benefit_id"], make_council_admin_headers())
    )
    assert analysis["status"] == "ACCEPTED"
    assert analysis["statewide_incremental_cost_cents"] == 143002800
    assert analysis["statewide_incremental_cost_cents"] != 143003375


def test_02_accepting_the_cost_benefit_analysis_absorbs_its_figures(api):
    """"When a `COST_BENEFIT` analysis is accepted, the proposal absorbs its
    figures: `statewide_incremental_cost_cents` is computed onto the proposal,
    `affected_permit_count` is copied across from the analysis, and
    `preliminary_benefit_cost_ratio` is computed." The first accepted analysis
    "moves the proposal `PENDING` → `PARTIAL`" and "touches `review_status` not at
    all".

    Design: Difficulty/combinatorial_formula/statewide_cost_rollup_permit_level_rounding_order_decides_result
    """
    world = fixtures.setup_screened_proposal(api)
    fixtures.file_cost_benefit_analysis(api, world)

    fixtures.review_analysis(api, world["cost_benefit_id"])

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["statewide_incremental_cost_cents"] == 143002800
    assert proposal["affected_permit_count"] == 2410
    assert proposal["preliminary_benefit_cost_ratio"] == 1.52
    assert proposal["analysis_status"] == "PARTIAL"
    assert proposal["review_status"] == "SCREENED"


def test_03_reopening_the_only_approval_leaves_no_residue_in_the_ledger(api):
    """"The cycle ledger is compensated by exactly the figures that were once
    added ... The compensation must leave no residue — a cycle whose last
    remaining approval is reopened reads zero on all three." Because "the
    compound gate that admitted the cycle to `RULEMAKING` no longer holds, the
    cycle reverts `RULEMAKING` → `DELIBERATION`".

    Design: Difficulty/compensating_invariant/reopen_compensates_cycle_cost_ledger_back_to_zero
    """
    world = fixtures.setup_rulemaking_cycle(api)

    fixtures.reopen_proposal(
        api, world, reason="New envelope test data invalidates the certified cost."
    )

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_incremental_cost_cents"] == 0
    assert cycle["approved_permit_backlog_count"] == 0
    assert cycle["approved_proposal_count"] == 0
    assert cycle["status"] == "DELIBERATION"


def test_04_reopening_clears_the_certified_figures_and_supersedes_analyses(api):
    """"The proposal moves to `RETURNED_FOR_REVISION`, `revision_round`
    increments by one, and the analysis dimension moves `COMPLETE` → `STALE`",
    "every child analysis of that proposal whose `status` is `ACCEPTED` moves
    `ACCEPTED` → `SUPERSEDED`", and "the proposal's
    `statewide_incremental_cost_cents`, `affected_permit_count`,
    `preliminary_benefit_cost_ratio` and `final_benefit_cost_ratio` are all
    cleared back to null".

    Design: Difficulty/compensating_invariant/reopen_compensates_cycle_cost_ledger_back_to_zero
    """
    world = fixtures.setup_rulemaking_cycle(api)

    fixtures.reopen_proposal(
        api, world, reason="New envelope test data invalidates the certified cost."
    )

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["review_status"] == "RETURNED_FOR_REVISION"
    assert proposal["analysis_status"] == "STALE"
    assert proposal["revision_round"] == 1
    assert proposal["statewide_incremental_cost_cents"] is None
    assert proposal["affected_permit_count"] is None
    assert proposal["preliminary_benefit_cost_ratio"] is None
    assert proposal["final_benefit_cost_ratio"] is None

    analyses, meta = validate_paginated(
        api.list_proposal_impact_analyses(
            world["proposal_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 2
    assert {row["status"] for row in analyses} == {"SUPERSEDED"}
