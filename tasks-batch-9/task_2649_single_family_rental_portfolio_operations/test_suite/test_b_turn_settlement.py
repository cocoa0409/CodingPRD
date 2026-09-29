"""The eight-step turn-holdback settlement and the realized input set that feeds it.

Both tests drive the make-ready cascade to completion and then read the whole settlement
group at once: one from a void that drains the live queue with a voided sibling that must
contribute nothing, the other from a completion landing exactly on the market's target so
the holdback tier is 0 rather than 1000.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import (
    assert_fields,
    assert_home_dimensions,
    assert_money_group,
    created,
    ok,
)
from test_helpers.constants import (
    ASSET_STABILIZED,
    CLOCK_SEP_04,
    CLOCK_SEP_06,
    OCC_VACANT,
    POSTURE_OPEN,
    PROJECT_RENT_READY,
    WO_COMPLETED,
    WO_VOIDED,
)


def test_the_voided_sibling_enters_neither_the_gross_turn_cost_nor_the_basis(api):
    """A void drains the queue, and 300000 -- not 600000 -- is what the settlement sees.

    PRD SS3.5: "a void can itself drain the project's live queue: if after the void no work
    order on the project remains in `PENDING_DISPATCH`, `DISPATCHED`, `ACCEPTED` or
    `IN_PROGRESS` and at least one is `COMPLETED`, the full five-hop make-ready cascade above
    fires from the void just as it would from a completion."  The first settlement step is
    filtered: "`gross_turn_cost_cents` is the sum of `actual_cost_cents` over every work order
    on the project whose `status` is `COMPLETED`. Voided work orders contribute nothing."  So is
    the realized renovation figure -- PRD SS3.2: "Its renovation figure is the sum of
    `actual_cost_cents` over every work order whose `status` is `COMPLETED` and whose
    `project_id` names any renovation project of that home; work orders sitting in `VOIDED`,
    `PENDING_DISPATCH`, `DISPATCHED`, `ACCEPTED` or `IN_PROGRESS` contribute nothing to that
    sum."  The money the void returns is the conserved kind -- PRD SS3.5: "if the work order
    named a `project_id`, that project's `committed_cost_cents` decreases by `quoted_cost_cents`
    and its `budget_remaining_cents` increases by the same amount".  The tier is the PRD's own:
    "If the turn ran 32 days, the overage is 2, which falls in the 1-to-3 band for a
    `holdback_rate_bps` of 1000", and PRD SS3.2: "`hold_sell_score_bps` is the case's
    `realized_yield_on_cost_bps` ... minus the market's `disposition_yield_floor_bps`" while
    "`disposition_flagged` is true exactly when that score is below zero".

    Design: Corner/calculations/realized_renovation_cost_counts_only_completed_work_orders
    """
    ctx = x.acquired_home(api)
    project = created(
        api.create_renovation_project(
            f.renovation_project_payload(ctx.home_id, 700000), x.OPS
        )
    )
    first = created(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]), x.OPS
        )
    )
    second = created(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.paint_id,
                project_id=project["id"],
                scheduled_start_date="2026-08-17",
                scheduled_end_date="2026-08-19",
            ),
            x.OPS,
        )
    )
    ok(api.lock_project_scope(project["id"], f.lock_scope_payload("2026-08-05"), x.OPS))
    ok(api.dispatch_work_order(first["id"], {}, x.OPS))
    x.set_clock(api, CLOCK_SEP_06)
    ok(
        api.complete_work_order(
            first["id"], f.complete_work_order_payload(300000, "2026-09-06"), x.OPS
        )
    )

    voided = ok(
        api.void_work_order(
            second["id"], f.void_work_order_payload("Second coat folded into WO1"), x.OPS
        )
    )
    assert_fields(voided, status=WO_VOIDED)
    assert_fields(ok(api.get_work_order(first["id"], x.OPS)), status=WO_COMPLETED)

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
        committed_cost_cents=300000,
        budget_remaining_cents=400000,
        gross_turn_cost_cents=300000,
        vendor_holdback_cents=30000,
        net_turn_cost_cents=270000,
    )

    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_fields(case, realized_yield_on_cost_bps=584)
    assert_money_group(
        case,
        realized_renovation_cost_cents=300000,
        realized_all_in_basis_cents=26050000,
        realized_noi_cents=1521184,
    )

    home = ok(api.get_home(ctx.home_id, x.OPS))
    assert_home_dimensions(home, ASSET_STABILIZED, OCC_VACANT, POSTURE_OPEN)
    assert_fields(home, hold_sell_score_bps=44, disposition_flagged=False)


def test_a_turn_landing_exactly_on_the_target_withholds_nothing(api):
    """Thirty days is inside the target, so the tier is 0 and the gross survives intact.

    PRD SS3.5: "`turn_days` is the number of whole days from `turn_started_on` inclusive to
    `rent_ready_on` exclusive -- so a turn that starts and finishes on the same date is zero
    days.  ... `overage_days` is `turn_days` less the market's `make_ready_target_days`, floored
    at zero: a turn at or inside the target has no overage.  ... `holdback_rate_bps` is a flat
    tier selected by the overage band, not a per-day accrual. Zero overage days give a rate of 0.
    One, two or three overage days give 1000."  And the worked case: "If the turn ran exactly 30
    days, the overage is 0, the rate is 0, `vendor_holdback_cents` is 0 and `net_turn_cost_cents`
    equals the gross 1520000 untouched."  The first hop stamps the date the count runs to: "The
    project moves `IN_PROGRESS -> RENT_READY` and its `rent_ready_on` is stamped with the current
    logical-clock date."  Hops 3 and 4 finish the cascade: "The home advances `RENOVATING ->
    STABILIZED`" and "`STABILIZED` is not a freezing asset state, so -- absent any blocking
    compliance obligation, unfunded-binder condition or excess of booked showings -- the posture
    leaves `FROZEN`".

    Design: Corner/calculations/turn_holdback_is_zero_at_exactly_the_make_ready_target
    """
    ctx = x.acquired_home(api)
    project = created(
        api.create_renovation_project(
            f.renovation_project_payload(ctx.home_id, 400000), x.OPS
        )
    )
    order = created(
        api.create_work_order(
            f.work_order_payload(ctx.home_id, ctx.paint_id, project_id=project["id"]), x.OPS
        )
    )
    ok(api.lock_project_scope(project["id"], f.lock_scope_payload("2026-08-05"), x.OPS))
    ok(api.dispatch_work_order(order["id"], {}, x.OPS))
    x.set_clock(api, CLOCK_SEP_04)

    completed = ok(
        api.complete_work_order(
            order["id"], f.complete_work_order_payload(300000, "2026-09-04"), x.OPS
        )
    )
    assert_fields(completed, status=WO_COMPLETED, completed_on="2026-09-04")
    assert_money_group(completed, actual_cost_cents=300000)

    settled = ok(api.get_renovation_project(project["id"], x.OPS))
    assert_fields(
        settled,
        status=PROJECT_RENT_READY,
        rent_ready_on="2026-09-04",
        turn_days=30,
        overage_days=0,
        holdback_rate_bps=0,
    )
    assert_money_group(
        settled,
        gross_turn_cost_cents=300000,
        vendor_holdback_cents=0,
        net_turn_cost_cents=300000,
    )

    assert_home_dimensions(
        ok(api.get_home(ctx.home_id, x.OPS)), ASSET_STABILIZED, OCC_VACANT, POSTURE_OPEN
    )
