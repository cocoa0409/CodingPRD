"""The two four-hop transitive cascades.

Both start from a single call that names one entity and end on a field of an entity the
caller never mentioned: a work-order completion reaches the showing calendar and the
underwriting case, and an accepted tax appeal reaches the home's disposition flag.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import assert_fields, assert_money_group, ok
from test_helpers.constants import (
    ASSET_STABILIZED,
    CLOCK_AUG_05,
    CLOCK_SEP_06,
    OBLIGATION_RESOLVED,
    OBLIGATION_TYPE_TAX_APPEAL,
    POSTURE_OPEN,
    PROJECT_RENT_READY,
    REVIEW_ACCEPT,
    SEVERITY_MINOR,
    SLOT_AVAILABLE,
    SLOT_BLOCKED_BY_POSTURE,
    WO_COMPLETED,
)


def test_completing_the_last_work_order_unblocks_the_calendar_and_realizes_the_yield(api):
    """One completion reaches the project, the home, a slot and the case.

    PRD SS3.5: "When that holds, five hops run in order as one atomic unit: 1. The project
    moves `IN_PROGRESS -> RENT_READY` and its `rent_ready_on` is stamped with the current
    logical-clock date. ... 3. The home advances `RENOVATING -> STABILIZED` ... 4. The home's
    `leasing_posture` is recomputed. `STABILIZED` is not a freezing asset state, so ... the
    posture leaves `FROZEN`, and every showing window on that home whose `status` is
    `BLOCKED_BY_POSTURE` returns to `AVAILABLE`. ... 5. The home's realized yield group is
    recomputed off actual spend, which also refreshes `hold_sell_score_bps` and
    `disposition_flagged` on the home's underwriting case."  PRD SS3.5 also fixes the
    settlement arithmetic: "If the turn ran 32 days, the overage is 2, which falls in the
    1-to-3 band for a `holdback_rate_bps` of 1000".

    Design: Difficulty/transitive_cascade/work_order_completion_cascades_four_hops_to_slot_unblock_and_realized_yield
    """
    ctx = x.acquired_home(api, general_template=False)
    slot = get_success_data(
        api.create_showing_slot(
            f.showing_slot_payload(
                ctx.home_id,
                starts_at="2026-09-10T15:00:00Z",
                ends_at="2026-09-10T15:30:00Z",
            ),
            x.AGENT,
        )
    )
    project = get_success_data(
        api.create_renovation_project(f.renovation_project_payload(ctx.home_id, 400000), x.OPS)
    )
    order = get_success_data(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]), x.OPS
        )
    )
    x.set_clock(api, CLOCK_AUG_05)
    get_success_data(api.lock_project_scope(project["id"], f.lock_scope_payload(), x.OPS))
    get_success_data(api.dispatch_work_order(order["id"], {}, x.OPS))
    locked_slot = ok(api.get_showing_slot(slot["id"], x.AGENT))
    assert_fields(locked_slot, status=SLOT_BLOCKED_BY_POSTURE)
    x.set_clock(api, CLOCK_SEP_06)

    completed = ok(
        api.complete_work_order(
            order["id"], f.complete_work_order_payload(300000, "2026-09-06"), x.OPS
        )
    )
    assert_fields(completed, status=WO_COMPLETED)

    settled = ok(api.get_renovation_project(project["id"], x.OPS))
    assert_fields(
        settled,
        status=PROJECT_RENT_READY,
        rent_ready_on="2026-09-06",
        turn_days=32,
        overage_days=2,
        holdback_rate_bps=1000,
    )
    assert_money_group(
        settled,
        gross_turn_cost_cents=300000,
        vendor_holdback_cents=30000,
        net_turn_cost_cents=270000,
    )

    home = ok(api.get_home(ctx.home_id, x.ANALYST))
    assert_fields(
        home,
        asset_status=ASSET_STABILIZED,
        leasing_posture=POSTURE_OPEN,
        hold_sell_score_bps=44,
        disposition_flagged=False,
    )
    assert_fields(ok(api.get_showing_slot(slot["id"], x.AGENT)), status=SLOT_AVAILABLE)

    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_money_group(
        case,
        realized_renovation_cost_cents=300000,
        realized_all_in_basis_cents=26050000,
        realized_noi_cents=1521184,
    )
    assert_fields(case, realized_yield_on_cost_bps=584)


def test_accepting_a_tax_appeal_clears_the_home_disposition_flag(api):
    """The appeal walks obligation to home to case and back to the flag.

    PRD SS3.9: "Worked through: a home assessed at 28000000 in a market whose `millage_bps` is
    125 carries a `property_tax_annual_cents` of 350000. The appeal settles at 24800000 with a
    `consultant_fee_bps` of 3000, so the reduction is 3200000, the `annual_tax_savings_cents`
    is 40000, the `consultant_fee_cents` is 12000 and the `net_tax_benefit_cents` is 28000.
    The home's `assessed_value_cents` becomes 24800000 and its `property_tax_annual_cents`
    becomes 310000. The case's `realized_noi_cents` rises from 1448541 to 1488541 and its
    `realized_yield_on_cost_bps` from 531 to 546, so against a `disposition_yield_floor_bps`
    of 540 the home's `hold_sell_score_bps` moves from -9 to 6 and its `disposition_flagged`
    flips from true to false -- a successful tax appeal is what takes a home off the
    disposition watch list."

    Design: Difficulty/transitive_cascade/tax_appeal_acceptance_cascades_four_hops_to_disposition_flag
    """
    ctx = x.three_order_scope(api)
    x.set_clock(api, CLOCK_AUG_05)
    get_success_data(api.lock_project_scope(ctx.project_id, f.lock_scope_payload(), x.OPS))
    for order_id in (ctx.paint_order_id, ctx.floor_a_order_id, ctx.floor_b_order_id):
        get_success_data(api.dispatch_work_order(order_id, {}, x.OPS))
    x.set_clock(api, CLOCK_SEP_06)
    for order_id, actual in (
        (ctx.paint_order_id, 310000),
        (ctx.floor_a_order_id, 640000),
        (ctx.floor_b_order_id, 570000),
    ):
        get_success_data(
            api.complete_work_order(
                order_id, f.complete_work_order_payload(actual, "2026-09-06"), x.OPS
            )
        )
    prospect = x.verified_prospect(api, ctx.market_id)
    screening = x.screened_application(api, ctx.home_id, prospect.prospect_id)
    lease = x.funded_draft_lease(api, screening.application_id)
    get_success_data(api.execute_lease(lease["id"], f.execute_lease_payload(), x.AGENT))

    before = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_fields(before, realized_yield_on_cost_bps=531)

    obligation = get_success_data(
        api.create_compliance_obligation(
            f.obligation_payload(
                ctx.home_id,
                OBLIGATION_TYPE_TAX_APPEAL,
                SEVERITY_MINOR,
                description="2026 Fulton County assessment appeal",
                assessed_value_cents=28000000,
                target_value_cents=24800000,
                consultant_fee_bps=3000,
            ),
            x.COMPLIANCE,
        )
    )
    get_success_data(
        api.plan_obligation(obligation["id"], f.plan_obligation_payload("2026-10-01"), x.COMPLIANCE)
    )
    get_success_data(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(settled_value_cents=24800000),
            x.COMPLIANCE,
        )
    )

    ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload(
                REVIEW_ACCEPT, review_note="board of assessors settled at 24800000"
            ),
            x.DIRECTOR,
        )
    )

    resolved = ok(api.get_compliance_obligation(obligation["id"], x.COMPLIANCE))
    assert_fields(resolved, status=OBLIGATION_RESOLVED)
    assert_money_group(
        resolved,
        annual_tax_savings_cents=40000,
        consultant_fee_cents=12000,
        net_tax_benefit_cents=28000,
    )

    home = ok(api.get_home(ctx.home_id, x.ANALYST))
    assert_money_group(
        home, assessed_value_cents=24800000, property_tax_annual_cents=310000
    )
    assert_fields(
        home,
        hold_sell_score_bps=6,
        disposition_flagged=False,
        leasing_posture=POSTURE_OPEN,
    )

    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_money_group(
        case, realized_renovation_cost_cents=1520000, realized_noi_cents=1488541
    )
    assert_fields(case, realized_yield_on_cost_bps=546)
