"""Calculation rules: bid line totals, project estimate, bid rank score
(estimated vs award-persisted), draw release amounts (provisional vs final,
round-then-subtract retainage), contractor average rating, and the
contract-value derived field.

All literal expected values are copied from the design indices, which pre-compute
them under the PRD's per-line-then-sum and round-half-up conventions.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    create_homeowner,
    create_qualified_contractor,
    create_draft_project,
    open_project,
    create_submitted_bid,
    award_bid,
    get_project_escrow,
    fund_escrow,
    request_draw,
    approve_draw,
    propose_change_order,
    current_bid_version,
    approve_change_order,
    setup_in_progress_project,
    request_approve_pay_draw,
    make_homeowner_headers,
    make_contractor_headers,
)


# ───────────────────────── Project estimate ─────────────────────────────────
def test_project_estimate_rounds_per_line_then_sums(api):
    """PRD §3.2: "the server computes that line's `estimated_total_cents` as the
    line's `quantity` multiplied by its `estimated_unit_cost_cents`, rounded
    half-up to whole cents."
    PRD §3.2: "returns the sum of every scope line's `estimated_total_cents` —
    each line rounded to whole cents first and then added together, in the same
    pinned per-line-then-sum order used for bids — together with the count of
    lines contributing to it as `line_count`."

    Design: Corner/calculations/project_estimate_round_per_line_then_sum
    """
    set_clock()
    homeowner = create_homeowner()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[
            {"description": "Tile", "quantity": 50, "unit": "SQFT", "estimated_unit_cost_cents": 333},
            {"description": "Trim", "quantity": 3, "unit": "UNIT", "estimated_unit_cost_cents": 111},
        ],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    res = api.get_project_estimate(project["id"], make_homeowner_headers(homeowner["id"]))
    data = validate_success(res, 200)
    # round(50*333)=16650 + round(3*111)=333 = 16983
    assert data["estimated_total_cents"] == 16983, data
    assert data["line_count"] == 2, data


def test_scope_line_item_estimated_total_computed_by_server(api):
    """PRD §3.2: "the server computes that line's `estimated_total_cents` as the
    line's `quantity` multiplied by its `estimated_unit_cost_cents`, rounded
    half-up to whole cents."

    Design: Corner/entities/scope_line_item_estimated_total_computed
    """
    set_clock()
    homeowner = create_homeowner()
    ho_headers = make_homeowner_headers(homeowner["id"])
    project = get_success_data(api.create_project(
        {"homeowner_id": homeowner["id"], "title": "CompProj", "budget_cap_cents": 500_000,
         "bid_deadline": "2026-07-01T00:00:00Z", "required_trade": "GENERAL", "min_rating": 0},
        ho_headers))
    res = api.create_scope_line_item(
        project["id"],
        {"description": "Tile", "quantity": 50, "unit": "SQFT", "estimated_unit_cost_cents": 333},
        ho_headers)
    line = validate_success(res, 201)
    assert line["estimated_total_cents"] == 16650, line  # round_half_up(50*333)


# ───────────────────────── Bid line totals ──────────────────────────────────
def test_bid_total_rounds_per_line_then_sums(api):
    """PRD §3.3: "The server computes each line's `line_total_cents` as that
    line's `quantity` multiplied by its `unit_price_cents`, rounded half-up to
    whole cents, and recomputes the bid's `total_cents` on every line addition as
    the sum of the rounded line totals — again rounding each line before summing."

    Design: Corner/calculations/bid_line_total_round_per_line_then_sum
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[
            {"description": "A", "quantity": 7, "unit": "UNIT", "estimated_unit_cost_cents": 100},
            {"description": "B", "quantity": 1, "unit": "LUMP", "estimated_unit_cost_cents": 2000},
        ],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(
        opened, contractor,
        line_specs=[(scope[0]["id"], 7, 145), (scope[1]["id"], 1, 2999)],
    )
    fetched = validate_success(
        api.get_bid(bid["id"], make_contractor_headers(contractor["id"])), 200)
    # round(7*145)=1015 + round(1*2999)=2999 = 4014
    assert fetched["total_cents"] == 4014, fetched


# ───────────────────────── Bid rank score ──────────────────────────────────
def test_bid_comparison_rank_score_three_input_normalization(api):
    """PRD §3.4: "The bid's `rank_score` is then the price component multiplied by
    0.5, plus the duration component multiplied by 0.3, plus the rating component
    multiplied by 0.2, with that sum rounded half-up to four decimal places."
    PRD §3.4: "The best bid is the one with the lowest `rank_score`; ties are
    broken first by lower `total_cents`, and any remaining tie by earlier
    `created_at`."

    Two bids, both contractors unrated (rating_norm 1.0). A(500000,10d):
    price_norm 0, dur_norm 0 -> 0.5*0+0.3*0+0.2*1.0 = 0.20.
    B(600000,30d): price_norm 1, dur_norm 1 -> 0.5*1+0.3*1+0.2*1.0 = 1.00.

    Design: Difficulty/combinatorial_formula/bid_rank_three_input_nonlinear_normalization
    """
    set_clock()
    homeowner = create_homeowner()
    ca = create_qualified_contractor()
    cb = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Deck", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 550_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    create_submitted_bid(opened, ca, line_specs=[(scope[0]["id"], 1, 500_000)], duration_days=10)
    create_submitted_bid(opened, cb, line_specs=[(scope[0]["id"], 1, 600_000)], duration_days=30)

    res = api.get_bid_comparison(opened["id"], make_homeowner_headers(homeowner["id"]))
    ranked = validate_success(res, 200)
    assert len(ranked) == 2, ranked
    by_id = {b["id"]: b for b in ranked}
    # Identify each bid by total_cents to avoid relying on ordering here.
    a = next(b for b in ranked if b["total_cents"] == 500_000)
    b = next(b for b in ranked if b["total_cents"] == 600_000)
    assert a["rank_score"] == pytest.approx(0.20, abs=1e-4), ranked
    assert b["rank_score"] == pytest.approx(1.00, abs=1e-4), ranked


def test_award_persists_three_input_normalized_rank_scores(api):
    """PRD §3.4: "The bid's `rank_score` is then the price component multiplied by
    0.5, plus the duration component multiplied by 0.3, plus the rating component
    multiplied by 0.2, with that sum rounded half-up to four decimal places."
    PRD §3.4: "the resulting `rank_score` is persisted on each of those pooled
    bids."

    Same three-input non-linear normalization applied at award time over the
    A(500000,10d)/B(600000,30d) pool (both unrated): A 0.20, B 1.00 persisted.

    Design: Difficulty/combinatorial_formula/bid_rank_three_input_nonlinear_normalization
    """
    set_clock()
    homeowner = create_homeowner()
    ca = create_qualified_contractor()
    cb = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Deck", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 550_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    ba = create_submitted_bid(opened, ca, line_specs=[(scope[0]["id"], 1, 500_000)], duration_days=10)
    bb = create_submitted_bid(opened, cb, line_specs=[(scope[0]["id"], 1, 600_000)], duration_days=30)
    award_bid(opened, homeowner, ba, opened["version"])

    ho = make_homeowner_headers(homeowner["id"])
    ra = validate_success(api.get_bid(ba["id"], ho), 200)
    rb = validate_success(api.get_bid(bb["id"], ho), 200)
    assert ra["rank_score"] == pytest.approx(0.20, abs=1e-4), ra
    assert rb["rank_score"] == pytest.approx(1.00, abs=1e-4), rb


def test_bid_comparison_returns_lowest_rank_score_first(api):
    """PRD §3.4: "The best bid is the one with the lowest `rank_score`; ties are
    broken first by lower `total_cents`, and any remaining tie by earlier
    `created_at`."
    PRD §3.4: "The advisory comparison applies this formula to whatever bids are
    submitted at the moment of the read and returns them ranked."

    Pool P(600000,30d), Q(700000,20d), R(650000,40d), all unrated. P has the
    lowest rank_score (0.35) so the comparison returns it first.

    Design: Difficulty/dual_variant_calc/bid_rank_estimated_vs_award_persistence_on_bid
    """
    set_clock()
    homeowner = create_homeowner()
    cp = create_qualified_contractor()
    cq = create_qualified_contractor()
    cr = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole job", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bp = create_submitted_bid(opened, cp, line_specs=[(scope[0]["id"], 1, 600_000)], duration_days=30)
    create_submitted_bid(opened, cq, line_specs=[(scope[0]["id"], 1, 700_000)], duration_days=20)
    create_submitted_bid(opened, cr, line_specs=[(scope[0]["id"], 1, 650_000)], duration_days=40)

    res = api.get_bid_comparison(opened["id"], make_homeowner_headers(homeowner["id"]))
    ranked = validate_success(res, 200)
    assert ranked[0]["id"] == bp["id"], ranked  # lowest rank_score 0.35


def test_award_persists_rank_score_on_pooled_bids(api):
    """PRD §3.4: "When the homeowner awards the project, the formula is applied
    over the submitted pool frozen at award time, and the resulting `rank_score`
    is persisted on each of those pooled bids; the recorded comparison stands as
    the audit trail of the decision."
    PRD §3.4: "The bid's `rank_score` is then the price component multiplied by
    0.5, plus the duration component multiplied by 0.3, plus the rating component
    multiplied by 0.2, with that sum rounded half-up to four decimal places."

    Pool P(600000,30d), Q(700000,20d), R(650000,40d), unrated. After award the
    persisted scores are P 0.35, Q 0.70, R 0.75.

    Design: Difficulty/dual_variant_calc/bid_rank_estimated_vs_award_persistence_on_bid
    """
    set_clock()
    homeowner = create_homeowner()
    cp = create_qualified_contractor()
    cq = create_qualified_contractor()
    cr = create_qualified_contractor()
    project, scope, _ = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole job", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": 600_000}],
        milestones=[{"sequence": 1, "release_pct": 1.0}],
    )
    opened = open_project(project, homeowner)
    bp = create_submitted_bid(opened, cp, line_specs=[(scope[0]["id"], 1, 600_000)], duration_days=30)
    bq = create_submitted_bid(opened, cq, line_specs=[(scope[0]["id"], 1, 700_000)], duration_days=20)
    br = create_submitted_bid(opened, cr, line_specs=[(scope[0]["id"], 1, 650_000)], duration_days=40)
    award_bid(opened, homeowner, bp, opened["version"])

    ho = make_homeowner_headers(homeowner["id"])
    rp = validate_success(api.get_bid(bp["id"], ho), 200)
    rq = validate_success(api.get_bid(bq["id"], ho), 200)
    rr = validate_success(api.get_bid(br["id"], ho), 200)
    assert rp["rank_score"] == pytest.approx(0.35, abs=1e-4), rp
    assert rq["rank_score"] == pytest.approx(0.70, abs=1e-4), rq
    assert rr["rank_score"] == pytest.approx(0.75, abs=1e-4), rr


# ───────────────────────── Draw release amounts ─────────────────────────────
def test_draw_retainage_rounded_then_subtracted(api):
    """PRD §3.6: "The `gross_amount_cents` is the project's `contract_value_cents`
    multiplied by the milestone's `release_pct`, rounded half-up to whole cents,
    read at the request instant."
    PRD §3.6: "For a non-final draw the `retainage_cents` is the
    `gross_amount_cents` multiplied by the retainage rate of ten percent, rounded
    half-up to whole cents — the rounding is applied to the retainage figure and
    then that rounded retainage is subtracted."

    contract_value 123450, release_pct 0.10 -> gross 12345; retainage
    round_half_up(1234.5)=1235; net 12345-1235=11110.

    Design: Difficulty/combinatorial_formula/draw_retainage_round_then_subtract_order
    """
    ctx = setup_in_progress_project(
        contract_value_cents=123_450,
        milestones=[{"sequence": 1, "release_pct": 0.10}, {"sequence": 2, "release_pct": 0.90}],
    )
    m1 = ctx["milestones"][0]
    draw = request_draw(ctx, m1, 11110)
    assert draw["gross_amount_cents"] == 12345, draw
    assert draw["retainage_cents"] == 1235, draw
    assert draw["net_release_cents"] == 11110, draw


def test_draw_retainage_round_half_up_at_second_boundary(api):
    """PRD §3.6: "For a non-final draw the `retainage_cents` is the
    `gross_amount_cents` multiplied by the retainage rate of ten percent, rounded
    half-up to whole cents — the rounding is applied to the retainage figure and
    then that rounded retainage is subtracted."

    A second exact-half boundary with different numbers confirms the round-half-up
    ordering: contract_value 23450, release_pct 0.10 -> gross 2345; retainage
    round_half_up(234.5)=235; net 2345-235=2110.

    Design: Difficulty/combinatorial_formula/draw_retainage_round_then_subtract_order
    """
    ctx = setup_in_progress_project(
        contract_value_cents=23_450,
        milestones=[{"sequence": 1, "release_pct": 0.10}, {"sequence": 2, "release_pct": 0.90}],
    )
    m1 = ctx["milestones"][0]
    draw = request_draw(ctx, m1, 2110)
    assert draw["gross_amount_cents"] == 2345, draw
    assert draw["retainage_cents"] == 235, draw
    assert draw["net_release_cents"] == 2110, draw


def test_draw_amounts_frozen_against_later_change_order(api):
    """PRD §3.6: "These frozen amounts are deliberately not re-opened later: a
    change order approved after a draw has been requested does not retroactively
    alter that already-requested draw."
    PRD §3.7: "On approval, the change order moves from `PROPOSED` to `APPROVED`,
    the project's `contract_value_cents` is increased by the `delta_cents`."

    Draw requested at contract_value 600000 (gross 240000, retainage 24000, net
    216000). A +100000 change order approved before draw approval lifts
    contract_value to 700000, but the draw keeps its frozen amounts.

    Design: Difficulty/dual_variant_calc/draw_release_provisional_vs_final_amounts_on_draw
    """
    ctx = setup_in_progress_project(
        contract_value_cents=600_000,
        milestones=[{"sequence": 1, "release_pct": 0.40}, {"sequence": 2, "release_pct": 0.60}],
        budget_cap_cents=1_000_000,
    )
    m1 = ctx["milestones"][0]
    draw = request_draw(ctx, m1, 216_000)

    co = propose_change_order(ctx, 100_000)
    approve_change_order(ctx, co, current_bid_version(ctx))

    approved_draw = approve_draw(ctx, draw)
    assert approved_draw["gross_amount_cents"] == 240_000, approved_draw
    assert approved_draw["retainage_cents"] == 24_000, approved_draw
    assert approved_draw["net_release_cents"] == 216_000, approved_draw

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    assert project["contract_value_cents"] == 700_000, project
    escrow = validate_success(api.get_escrow(ctx["escrow"]["id"], ho), 200)
    assert escrow["retained_cents"] == 24_000, escrow


def test_draw_amounts_match_provisional_at_request(api):
    """PRD §3.6: "At request time the server computes the draw's amounts and
    freezes them onto the draw. The `gross_amount_cents` is the project's
    `contract_value_cents` multiplied by the milestone's `release_pct`, rounded
    half-up to whole cents, read at the request instant."

    contract_value 600000, release_pct 0.40 -> gross 240000, retainage 24000,
    net 216000 at the request instant.

    Design: Difficulty/dual_variant_calc/draw_release_provisional_vs_final_amounts_on_draw
    """
    ctx = setup_in_progress_project(
        contract_value_cents=600_000,
        milestones=[{"sequence": 1, "release_pct": 0.40}, {"sequence": 2, "release_pct": 0.60}],
    )
    m1 = ctx["milestones"][0]
    draw = request_draw(ctx, m1, 216_000)
    assert draw["gross_amount_cents"] == 240_000, draw
    assert draw["retainage_cents"] == 24_000, draw
    assert draw["net_release_cents"] == 216_000, draw


# ───────────────────────── Contractor average rating ────────────────────────
def test_contractor_average_rating_recomputed_over_ratings(api):
    """PRD §3.8: "Rating adds the new star value to the contractor's `rating_sum`,
    increments the contractor's `rating_count` by one, and recomputes the
    contractor's `average_rating` as `rating_sum` divided by `rating_count`,
    rounded half-up to two decimal places — or zero when the contractor has no
    ratings yet."

    Two completed projects rated 5 then 4 -> rating_sum 9, rating_count 2,
    average_rating round_half_up(4.5)=4.5.

    Design: Corner/calculations/contractor_average_rating_recompute
    """
    set_clock()
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()
    ho = make_homeowner_headers(homeowner["id"])

    def complete_and_rate(stars):
        project, scope, milestones = create_draft_project(
            homeowner,
            scope_lines=[{"description": "Whole job", "quantity": 1, "unit": "LUMP",
                          "estimated_unit_cost_cents": 600_000}],
            milestones=[{"sequence": 1, "release_pct": 1.0}],
        )
        opened = open_project(project, homeowner)
        bid = create_submitted_bid(opened, contractor, line_specs=[(scope[0]["id"], 1, 600_000)])
        award_bid(opened, homeowner, bid, opened["version"])
        escrow = get_project_escrow(opened, homeowner)
        fund_escrow(escrow, 600_000)
        ctx = {"homeowner": homeowner, "contractor": contractor, "project": opened}
        request_approve_pay_draw(ctx, milestones[0], 600_000)
        validate_success(api.complete_project(opened["id"], ho), 200)
        return validate_success(
            api.rate_contractor(opened["id"], {"stars": stars}, ho), 200)

    complete_and_rate(5)
    rated = complete_and_rate(4)
    assert rated["rating_sum"] == 9, rated
    assert rated["rating_count"] == 2, rated
    assert rated["average_rating"] == pytest.approx(4.5, abs=1e-9), rated


# ───────────────────────── Contract value reconciliation ───────────────────
def test_contract_value_reconciles_after_change_order_approval(api):
    """PRD §3.7: "On approval, the change order moves from `PROPOSED` to
    `APPROVED`, the project's `contract_value_cents` is increased by the
    `delta_cents` (a negative delta decreasing it), and the awarded bid's
    `version` is incremented by one."

    Awarded total 600000 + approved +10000 change order -> contract_value 610000.

    Design: Corner/cross_cutting_complexity_layers/derived_field_contract_value_reconciles_on_change_order
    """
    ctx = setup_in_progress_project(contract_value_cents=600_000)
    co = propose_change_order(ctx, 10_000)
    approved = approve_change_order(ctx, co, current_bid_version(ctx))
    assert approved["status"] == "APPROVED", approved

    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    project = validate_success(api.get_project(ctx["project"]["id"], ho), 200)
    assert project["contract_value_cents"] == 610_000, project
