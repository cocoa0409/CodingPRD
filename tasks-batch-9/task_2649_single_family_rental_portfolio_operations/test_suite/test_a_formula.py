"""The two multi-step formulas whose only correct evaluation order is the declared one.

Both rules are about *where* the rounding and the ceiling sit inside an aggregation: the
scope benchmark rounds per line before summing, and the turn holdback caps against the
gross turn cost rather than against the raw holdback.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import assert_fields, assert_money_group, created, ok
from test_helpers.constants import (
    CASE_DRAFT,
    CLOCK_AUG_01,
    CLOCK_AUG_05,
    CLOCK_SEP_08,
    PROJECT_RENT_READY,
)


def test_planned_budget_rounds_per_line_and_lands_one_cent_below_index_the_sum(api):
    """Three lines round to 1479843, not to the 1479844 of indexing the sum.

    PRD SS3.2: "Consider a market whose `cost_index_bps` is 10250, with three lines -- a
    floor scope at 475 cents per unit for 1150 units, an HVAC replacement at 612450 cents
    for one unit, and an interior paint at 285050 cents for one unit. Rounding per line
    gives 559906, 627761 and 292176 for a total of 1479843. Summing first and indexing once
    gives 1479844. The first figure is the one this API stores."  PRD SS2.5 states the same
    rule generally: "a benchmark total is rounded once **per scope line** and only the
    already-rounded per-line figures are summed".

    Design: Difficulty/combinatorial_formula/scope_benchmark_per_line_rounding_beats_index_the_sum_by_one_cent
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    templates = x.three_trade_catalogue(api)
    home = x.create_home(api, market["id"])

    case = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"],
                home["version"],
                [
                    f.scope_line(templates.floor["id"], 1150),
                    f.scope_line(templates.hvac["id"], 1),
                    f.scope_line(templates.paint["id"], 1),
                ],
            ),
            x.ANALYST,
        )
    )
    assert_money_group(
        case,
        planned_renovation_budget_cents=1479843,
        underwritten_all_in_basis_cents=27229843,
        underwritten_effective_gross_income_cents=2425200,
        underwritten_noi_cents=1521184,
    )
    assert case["planned_renovation_budget_cents"] != 1479844
    assert_fields(case, underwritten_yield_on_cost_bps=559, status=CASE_DRAFT)


def test_turn_holdback_cap_is_keyed_on_gross_turn_cost(api):
    """A 34-day turn caps the holdback at 228000, never at 182400.

    PRD SS3.5: "If instead the turn ran 34 days, the overage is 4, which crosses into the
    4-to-7 band for a rate of 2000; the raw holdback is 304000, which exceeds the cap of
    228000, so the cap binds -- `vendor_holdback_cents` is 228000 and `net_turn_cost_cents`
    is 1292000."  PRD SS3.5 step 6: "The cap is always computed against the **gross** turn
    cost, never against the raw holdback."

    Design: Difficulty/combinatorial_formula/turn_holdback_cap_keyed_on_gross_not_net_turn_cost
    """
    ctx = x.three_order_scope(api)
    x.set_clock(api, CLOCK_AUG_05)
    get_success_data(api.lock_project_scope(ctx.project_id, f.lock_scope_payload(), x.OPS))
    for order_id in (ctx.paint_order_id, ctx.floor_a_order_id, ctx.floor_b_order_id):
        get_success_data(api.dispatch_work_order(order_id, {}, x.OPS))
    x.set_clock(api, CLOCK_SEP_08)
    get_success_data(
        api.complete_work_order(
            ctx.paint_order_id, f.complete_work_order_payload(310000, "2026-09-08"), x.OPS
        )
    )
    get_success_data(
        api.complete_work_order(
            ctx.floor_a_order_id, f.complete_work_order_payload(640000, "2026-09-08"), x.OPS
        )
    )

    ok(
        api.complete_work_order(
            ctx.floor_b_order_id, f.complete_work_order_payload(570000, "2026-09-08"), x.OPS
        )
    )

    project = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_fields(
        project,
        status=PROJECT_RENT_READY,
        rent_ready_on="2026-09-08",
        turn_days=34,
        overage_days=4,
        holdback_rate_bps=2000,
    )
    assert_money_group(
        project,
        gross_turn_cost_cents=1520000,
        vendor_holdback_cents=228000,
        net_turn_cost_cents=1292000,
        committed_cost_cents=1510000,
        budget_remaining_cents=90000,
    )
    assert project["vendor_holdback_cents"] != 182400
