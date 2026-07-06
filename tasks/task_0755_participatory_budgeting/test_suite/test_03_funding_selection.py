"""Funding selection: waterfall allocation, ledger cascade, budget conservation, OCC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    scenario_multi_proposal_on_ballot, scenario_selected_proposal,
    scenario_empty_selection_ready,
    open_ballot, add_entry, cast_ballot, transition, run_selection,
    cycle_version, get_category, new_cycle, new_category,
    make_resident_headers, TEST_USERS,
)

ADMIN = TEST_USERS["budget_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / funding_selection_waterfall_min_caps
# ---------------------------------------------------------------------------

def _waterfall_setup(api):
    sc = scenario_multi_proposal_on_ballot(api, 
        voting_method="ALLOCATION", n_residents=1,
        total_budget=92400, per_project_cap=60000, per_voter_cap=1_000_000, category_cap=100000,
        proposal_specs=[
            {"title": "P1", "line_items": [{"unit_cost_cents": 50000, "quantity": 1, "contingency_pct": 0.10}]},
            {"title": "P2", "line_items": [{"unit_cost_cents": 40000, "quantity": 1, "contingency_pct": 0.10}]},
            {"title": "P3", "line_items": [{"unit_cost_cents": 30000, "quantity": 1, "contingency_pct": 0.10}]},
        ],
    )
    p1, p2, p3 = sc["proposals"]
    rid = sc["residents"][0]
    bid = open_ballot(api, sc["cyc"], rid)["id"]
    add_entry(api, bid, rid, p1, allocated_cents=3000)
    add_entry(api, bid, rid, p2, allocated_cents=2000)
    add_entry(api, bid, rid, p3, allocated_cents=1000)
    cast_ballot(api, bid, rid)
    transition(api, sc["cyc"], "SELECTION")
    run = run_selection(api, sc["cyc"])
    sc["run"] = run
    sc["p1"], sc["p2"], sc["p3"] = p1, p2, p3
    return sc


def test_waterfall_skips_over_unaffordable_and_funds_cheaper_lower_ranked(api):
    """PRD §3.7: "If neither holds — the cost is within the per-project cap but would overrun
    the remaining total or the remaining category pool — the proposal moves to `NOT_SELECTED`
    with `awarded_cents` left at zero, and the walk continues in a waterfall fashion: a
    cheaper, lower-ranked proposal further down the slate may still fit within what remains."

    Design: Difficulty/combinatorial_formula/funding_selection_waterfall_min_caps
    """
    sc = _waterfall_setup(api)
    p1 = validate_success(api.get_proposal(sc["p1"], ADMIN))
    p2 = validate_success(api.get_proposal(sc["p2"], ADMIN))
    p3 = validate_success(api.get_proposal(sc["p3"], ADMIN))
    assert p1["status"] == "SELECTED" and p1["awarded_cents"] == 57750, p1
    assert p2["status"] == "NOT_SELECTED" and p2["awarded_cents"] == 0, p2
    assert p3["status"] == "SELECTED" and p3["awarded_cents"] == 34650, p3


def test_waterfall_inclusive_boundary_fills_pool_exactly(api):
    """PRD §3.7: "This boundary is inclusive, so a proposal whose cost exactly equals the
    smaller remaining pool is funded."

    Design: Difficulty/combinatorial_formula/funding_selection_waterfall_min_caps
    """
    sc = _waterfall_setup(api)
    run = sc["run"]
    assert run["selected_count"] == 2, run
    assert run["total_awarded_cents"] == 92400, run
    cycle = validate_success(api.get_budget_cycle(sc["cyc"], ADMIN))
    assert cycle["uncommitted_cents"] == 0, "P3 (34650) exactly fills the 34650 remaining pool"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / selection_award_cascades_to_category_and_cycle_ledger
# ---------------------------------------------------------------------------

def test_award_counts_into_owning_category_committed(api):
    """PRD §2.6: "A category's `committed_cents` is the sum of `awarded_cents` over the
    proposals in that category whose status is `SELECTED`, `IN_IMPLEMENTATION`, or
    `COMPLETED`."

    Design: Difficulty/transitive_cascade/selection_award_cascades_to_category_and_cycle_ledger
    """
    sc = scenario_selected_proposal(api, allocated_cents=5000)
    prop = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert prop["awarded_cents"] == 34650, prop
    cat = get_category(api, sc["cyc"], sc["cat"])
    assert cat["committed_cents"] == 34650, cat


def test_award_rolls_up_to_cycle_total_and_uncommitted(api):
    """PRD §2.6: "the cycle's `total_committed_cents` is the sum of `committed_cents` across
    all of that cycle's categories, and the cycle's `uncommitted_cents` — the conserved
    quantity of the whole program — is `total_budget_cents` minus `total_committed_cents`."

    Design: Difficulty/transitive_cascade/selection_award_cascades_to_category_and_cycle_ledger
    """
    sc = scenario_selected_proposal(api, allocated_cents=5000)
    cycle = validate_success(api.get_budget_cycle(sc["cyc"], ADMIN))
    assert cycle["total_committed_cents"] == 34650, cycle
    assert cycle["uncommitted_cents"] == 65350, cycle


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / budget_conservation_award_then_cancel
# ---------------------------------------------------------------------------

def test_cancel_resets_award_and_status(api):
    """PRD §3.8: "Cancellation is a compensating action: it resets the proposal's
    `awarded_cents` to zero, recomputes the owning category's `committed_cents`, and rolls
    that change up to restore the cycle's `total_committed_cents` and `uncommitted_cents`,
    returning the released money to the uncommitted pool; the proposal's `version` increments
    by one."

    Design: Difficulty/compensating_invariant/budget_conservation_award_then_cancel
    """
    sc = scenario_selected_proposal(api, allocated_cents=5000)
    cancelled = validate_success(api.cancel_funding(sc["pid"], ADMIN))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["awarded_cents"] == 0


def test_cancel_restores_ledger_to_original(api):
    """PRD §2.6: "When a proposal is cancelled, its `awarded_cents` is reset to zero and these
    same four quantities are recomputed, restoring the released money to the uncommitted pool."

    Design: Difficulty/compensating_invariant/budget_conservation_award_then_cancel
    """
    sc = scenario_selected_proposal(api, allocated_cents=5000)
    validate_success(api.cancel_funding(sc["pid"], ADMIN))
    cat = get_category(api, sc["cyc"], sc["cat"])
    assert cat["committed_cents"] == 0, cat
    cycle = validate_success(api.get_budget_cycle(sc["cyc"], ADMIN))
    assert cycle["uncommitted_cents"] == 100000, "released money returns; no budget drift"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / selection_over_empty_ballot_slate_funds_nothing
# ---------------------------------------------------------------------------

def test_selection_over_empty_slate_funds_nothing(api):
    """PRD §3.7: "The slate consists of the proposals in the cycle whose status is
    `ON_BALLOT`, and their inputs are the finalized `estimated_cost_cents` and the running
    `vote_score`."
    PRD §3.7: "Each run records how many proposals it funded in `selected_count`, the sum it
    awarded in `total_awarded_cents`, and an `is_current` flag"

    Design: Difficulty/boundary_precision_check/selection_over_empty_ballot_slate_funds_nothing
    """
    sc = scenario_empty_selection_ready(api, total_budget=100000)
    run = validate_success(
        api.create_selection_run(sc["cyc"], {"expected_budgetcycle_version": sc["ver"]}, ADMIN),
        expected_status=201,
    )
    assert run["selected_count"] == 0, run
    assert run["total_awarded_cents"] == 0, run


def test_selection_over_empty_slate_leaves_full_budget_uncommitted(api):
    """PRD §2.6: "the cycle's `uncommitted_cents` — the conserved quantity of the whole
    program — is `total_budget_cents` minus `total_committed_cents`."

    Design: Difficulty/boundary_precision_check/selection_over_empty_ballot_slate_funds_nothing
    """
    sc = scenario_empty_selection_ready(api, total_budget=100000)
    validate_success(
        api.create_selection_run(sc["cyc"], {"expected_budgetcycle_version": sc["ver"]}, ADMIN),
        expected_status=201,
    )
    cycle = validate_success(api.get_budget_cycle(sc["cyc"], ADMIN))
    assert cycle["uncommitted_cents"] == 100000, cycle


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / corner_selection_run_stale_version_conflict
# ---------------------------------------------------------------------------

def test_second_selection_run_with_stale_version_rejected(api):
    """PRD §2.10: "If that value does not equal the cycle's current `version`, the run is
    rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
    PRD §2.10: "the first run advances the cycle's `version`, so any writer still holding the
    pre-run version is working from a superseded view of the results and must re-read before
    running again."

    Design: Corner/cross_cutting_complexity_layers/corner_selection_run_stale_version_conflict
    """
    sc = scenario_empty_selection_ready(api, )
    # First run succeeds and advances the cycle version.
    validate_success(
        api.create_selection_run(sc["cyc"], {"expected_budgetcycle_version": sc["ver"]}, ADMIN),
        expected_status=201,
    )
    # Second run reuses the now-stale pre-run version.
    resp = api.create_selection_run(sc["cyc"], {"expected_budgetcycle_version": sc["ver"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: consistency_model / corner_immediate_category_ledger_initialized
# ---------------------------------------------------------------------------

def test_new_category_ledger_initialized_immediately(api):
    """PRD §2.6: "That category's `remaining_cap_cents` is its `category_budget_cap_cents`
    minus its `committed_cents`."
    PRD §3.2: "its computed `committed_cents` and `remaining_cap_cents` follow the ledger
    rules of §2.6."

    Design: Corner/consistency_model/corner_immediate_category_ledger_initialized
    """
    cyc = new_cycle(api, name="PBim")
    cat = validate_success(
        api.create_category(cyc["id"], {"name": "Gen", "category_budget_cap_cents": 50000}, ADMIN),
        expected_status=201,
    )
    assert cat["committed_cents"] == 0
    assert cat["remaining_cap_cents"] == 50000
