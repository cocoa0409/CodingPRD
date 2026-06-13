"""Award and escrow: the budget-cap boundary on award, the release_pct-sum
boundary on open, the award cascade and its immediate visibility, OCC staleness
on award, and the fund-deposit equality rule.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    set_clock,
    create_homeowner,
    create_qualified_contractor,
    create_draft_project,
    open_project,
    create_submitted_bid,
    award_bid,
    get_project_escrow,
    make_homeowner_headers,
    make_contractor_headers,
)


# ───────────────────────── Budget-cap boundary on award ────────────────────
def test_award_bid_equal_to_budget_cap_accepted(api):
    """PRD §3.4: "the named bid's `total_cents` must not exceed the project's
    `budget_cap_cents` (otherwise the award is rejected with `ERR_BUDGET_EXCEEDED`)."

    Bid total == budget_cap (600000 == 600000) is at the boundary and accepted
    because the rule is "must not exceed" (i.e. <= is allowed).

    Design: Difficulty/boundary_precision_check/award_budget_cap_exact_vs_over_by_one
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
        budget_cap_cents=600_000,
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    res = api.award_project(
        opened["id"],
        {"bid_id": bid["id"], "expected_project_version": opened["version"]},
        make_homeowner_headers(homeowner["id"]))
    awarded = validate_success(res, 200)
    assert awarded["status"] == "AWARDED", awarded


def test_award_bid_one_over_budget_cap_rejected(api):
    """PRD §3.4: "the named bid's `total_cents` must not exceed the project's
    `budget_cap_cents` (otherwise the award is rejected with `ERR_BUDGET_EXCEEDED`)."

    Bid total == budget_cap + 1 (600001 vs 600000) exceeds the cap and is
    rejected; the project stays OPEN_FOR_BIDS.

    Design: Difficulty/boundary_precision_check/award_budget_cap_exact_vs_over_by_one
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
        budget_cap_cents=600_000,
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_001)])
    res = api.award_project(
        opened["id"],
        {"bid_id": bid["id"], "expected_project_version": opened["version"]},
        make_homeowner_headers(homeowner["id"]))
    validate_error(res, "ERR_BUDGET_EXCEEDED")
    project_after = validate_success(
        api.get_project(opened["id"], make_homeowner_headers(homeowner["id"])), 200)
    assert project_after["status"] == "OPEN_FOR_BIDS", project_after


# ───────────────────────── release_pct-sum boundary on open ────────────────
def test_open_with_release_pct_sum_exactly_one_succeeds(api):
    """PRD §3.3: "The homeowner may open the project only when all of the following
    hold: at least one scope line item exists, at least one milestone exists, the
    sum of all the project's milestone `release_pct` values equals exactly 1.0,
    and the current clock is before the project's `bid_deadline`."

    Milestones 0.40 + 0.60 == 1.0 at the boundary; open succeeds.

    Design: Difficulty/boundary_precision_check/open_release_pct_sum_exactly_one_vs_under
    """
    set_clock()
    homeowner = create_homeowner()
    project, _scope, _ms = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 0.40}, {"sequence": 2, "release_pct": 0.60}],
    )
    opened = validate_success(
        api.open_project(project["id"], make_homeowner_headers(homeowner["id"])), 200)
    assert opened["status"] == "OPEN_FOR_BIDS", opened


def test_open_with_release_pct_sum_under_one_rejected(api):
    """PRD §3.3: "If the milestone percentages do not sum to exactly one, the open
    is rejected with `ERR_MILESTONE_PCT_INVALID`."

    Milestones 0.40 + 0.59 == 0.99 fall short of 1.0; open is rejected and the
    project stays DRAFT.

    Design: Difficulty/boundary_precision_check/open_release_pct_sum_exactly_one_vs_under
    """
    set_clock()
    homeowner = create_homeowner()
    project, _scope, _ms = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 0.40}, {"sequence": 2, "release_pct": 0.59}],
    )
    res = api.open_project(project["id"], make_homeowner_headers(homeowner["id"]))
    validate_error(res, "ERR_MILESTONE_PCT_INVALID")
    after = validate_success(
        api.get_project(project["id"], make_homeowner_headers(homeowner["id"])), 200)
    assert after["status"] == "DRAFT", after


# ───────────────────────── Award cascade (queue B) ─────────────────────────
def test_award_cascades_sibling_bids_to_rejected(api):
    """PRD §3.4: "every other bid on the project that is in `SUBMITTED` or
    `REVISING` status is cascaded to the terminal `REJECTED` state; the project's
    `awarded_bid_id` is set to the winning bid; `scope_locked` is set to true;
    the project's `contract_value_cents` is set to the awarded bid's `total_cents`."

    Design: Corner/state_machines/award_cascade_rejects_sibling_bids
    """
    set_clock()
    homeowner = create_homeowner()
    c1 = create_qualified_contractor()
    c2 = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    b_win = create_submitted_bid(opened, c1, line_specs=[(scope[0]["id"], 1, 500_000)], duration_days=30)
    b_lose = create_submitted_bid(opened, c2, line_specs=[(scope[0]["id"], 1, 550_000)], duration_days=40)
    award_bid(opened, homeowner, b_win, opened["version"])

    ho = make_homeowner_headers(homeowner["id"])
    win_after = validate_success(api.get_bid(b_win["id"], ho), 200)
    lose_after = validate_success(api.get_bid(b_lose["id"], ho), 200)
    proj_after = validate_success(api.get_project(opened["id"], ho), 200)
    assert win_after["status"] == "AWARDED", win_after
    assert lose_after["status"] == "REJECTED", lose_after
    assert proj_after["scope_locked"] is True, proj_after
    assert proj_after["contract_value_cents"] == 500_000, proj_after


def test_award_response_reflects_changes_immediately(api):
    """PRD §3.4: "the project's `awarded_bid_id` is set to the winning bid;
    `scope_locked` is set to true; the project's `contract_value_cents` is set to
    the awarded bid's `total_cents` (no change orders exist yet)."

    Design: Corner/consistency_model/immediate_award_visible_in_same_response
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 500_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 500_000)])
    res = api.award_project(
        opened["id"],
        {"bid_id": bid["id"], "expected_project_version": opened["version"]},
        make_homeowner_headers(homeowner["id"]))
    awarded = validate_success(res, 200)
    assert awarded["awarded_bid_id"] == bid["id"], awarded
    assert awarded["scope_locked"] is True, awarded
    assert awarded["contract_value_cents"] == 500_000, awarded


# ───────────────────────── OCC stale project version (queue B) ─────────────
def test_award_with_stale_project_version_rejected(api):
    """PRD §2.9: "The award request must carry `expected_project_version`, and the
    value must equal the target project's current `version`. If a prior award (or
    any other mutation) has already advanced the project's version since the
    client last read it, the client's view is stale — the project may already have
    left its open-for-bids state — and the award is rejected with
    `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    A first award advances Project.version; a second award still carrying the
    pre-award version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_award_stale_project_version
    """
    set_clock()
    homeowner = create_homeowner()
    c1 = create_qualified_contractor()
    c2 = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    stale_version = opened["version"]
    b1 = create_submitted_bid(opened, c1, line_specs=[(scope[0]["id"], 1, 500_000)], duration_days=30)
    b2 = create_submitted_bid(opened, c2, line_specs=[(scope[0]["id"], 1, 510_000)], duration_days=35)
    award_bid(opened, homeowner, b1, stale_version)  # bumps Project.version

    res = api.award_project(
        opened["id"],
        {"bid_id": b2["id"], "expected_project_version": stale_version},
        make_homeowner_headers(homeowner["id"]))
    validate_error(res, "ERR_STALE_PROJECT_VERSION")
    ho = make_homeowner_headers(homeowner["id"])
    assert validate_success(api.get_bid(b1["id"], ho), 200)["status"] == "AWARDED"


# ───────────────────────── Fund deposit equality (queue B) ─────────────────
def test_fund_with_wrong_deposit_rejected(api):
    """PRD §3.5: "The escrow agent funds it by supplying a `deposit_cents` amount,
    which must exactly equal the project's current `contract_value_cents`; a
    deposit of any other amount is rejected with `ERR_INSUFFICIENT_ESCROW`."

    contract_value 600000, fund attempt 500000 -> rejected; project stays AWARDED,
    escrow stays UNFUNDED.

    Design: Corner/errors/fund_deposit_not_equal_contract_value
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
    award_bid(opened, homeowner, bid, opened["version"])
    escrow = get_project_escrow(opened, homeowner)

    from test_helpers import TEST_USERS
    res = api.fund_escrow(escrow["id"], {"deposit_cents": 500_000},
                          TEST_USERS["escrow_agent_headers"])
    validate_error(res, "ERR_INSUFFICIENT_ESCROW")

    ho = make_homeowner_headers(homeowner["id"])
    assert validate_success(api.get_project(opened["id"], ho), 200)["status"] == "AWARDED"
    assert validate_success(api.get_escrow(escrow["id"], ho), 200)["status"] == "UNFUNDED"
