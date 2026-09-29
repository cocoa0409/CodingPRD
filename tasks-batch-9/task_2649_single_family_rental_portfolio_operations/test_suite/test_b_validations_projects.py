"""Project guards that read rows the payload never names: the case table and the ledger.

A project refusal is never about the request in isolation -- it is about the home's
underwriting history, its other live projects, or money already committed against it -- and
the terminal project proves the same payload can be legal as standalone maintenance.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_BUDGET_BELOW_COMMITTED,
    ERR_CASE_NOT_APPROVED,
    ERR_DUPLICATE_PROJECT_FOR_HOME,
    ERR_PROJECT_SCOPE_LOCKED,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    PROJECT_RENT_READY,
    PROJECT_SCOPING,
    WO_PENDING_DISPATCH,
)


def test_three_project_guards_each_read_a_different_row_of_the_same_home(api):
    """No approved case, then a second live project, then a budget under the commitment.

    PRD SS3.3: "A project can only be opened for a home that already has an underwriting case
    in `APPROVED`; if it has none, the request is refused with `ERR_CASE_NOT_APPROVED`. A home
    may not carry two live projects at once: if it already has a project whose `status` is
    `SCOPING` or `IN_PROGRESS`, the request is refused with `ERR_DUPLICATE_PROJECT_FOR_HOME`."
    PRD SS3.3 on the ledger: "A project's `approved_budget_cents` may be revised later by an
    `OperationsManager` or a `RegionalDirector`, which resets `budget_remaining_cents` to the
    new `approved_budget_cents` less the current `committed_cost_cents` and increments the
    project's `version` by 1. Lowering the budget below money already committed would break the
    conserved money identity, so a revision whose `approved_budget_cents` is less than
    `committed_cost_cents` is refused with `ERR_BUDGET_BELOW_COMMITTED`."  The commitment
    itself is PRD SS3.3's own: "when a `project_id` is supplied, the quote is added to the
    project's `committed_cost_cents` and subtracted from `budget_remaining_cents`", and PRD
    SS2.9 keeps the pair conserved: "`committed_cost_cents` plus `budget_remaining_cents`
    always equals `approved_budget_cents`."

    Design: Corner/validations/project_creation_and_budget_guards_depend_on_other_entities
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])

    failed(
        api.create_renovation_project(f.renovation_project_payload(home["id"], 700000), x.OPS),
        ERR_CASE_NOT_APPROVED,
    )

    x.underwrite_and_approve(
        api, home["id"], home["version"], [f.scope_line(paint["id"], 1)]
    )
    project = created(
        api.create_renovation_project(f.renovation_project_payload(home["id"], 700000), x.OPS)
    )
    assert_money_group(
        project,
        approved_budget_cents=700000,
        committed_cost_cents=0,
        budget_remaining_cents=700000,
    )

    failed(
        api.create_renovation_project(f.turn_project_payload(home["id"], 200000), x.OPS),
        ERR_DUPLICATE_PROJECT_FOR_HOME,
    )

    created(
        api.create_work_order(
            f.work_order_payload(home["id"], paint["id"], project_id=project["id"]), x.OPS
        )
    )
    committed = ok(api.get_renovation_project(project["id"], x.OPS))
    assert_money_group(
        committed, committed_cost_cents=300000, budget_remaining_cents=400000
    )

    failed(
        api.set_project_budget(project["id"], f.budget_payload(200000), x.OPS),
        ERR_BUDGET_BELOW_COMMITTED,
    )
    assert_money_group(
        ok(api.get_renovation_project(project["id"], x.OPS)),
        approved_budget_cents=700000,
        committed_cost_cents=300000,
        budget_remaining_cents=400000,
    )

    raised = ok(api.set_project_budget(project["id"], f.budget_payload(800000), x.DIRECTOR))
    assert_money_group(
        raised,
        approved_budget_cents=800000,
        committed_cost_cents=300000,
        budget_remaining_cents=500000,
    )
    assert_fields(raised, status=PROJECT_SCOPING)
    assert (
        raised["committed_cost_cents"] + raised["budget_remaining_cents"]
        == raised["approved_budget_cents"]
    )


def test_a_rent_ready_project_takes_no_more_work_but_the_home_still_can(api):
    """The refusal is about the project's terminal status, not about the 100000 left in it.

    PRD SS3.3: "a project that has already reached `RENT_READY` accepts no further work orders
    and refuses them with `ERR_PROJECT_SCOPE_LOCKED`."  That guard outranks both fiscal gates
    -- PRD SS2.7 places "**Rank 304 -- project scope already locked out.**
    `ERR_PROJECT_SCOPE_LOCKED` (409) on work-order creation" above "**Rank 604 -- cost variance
    above tolerance.**" and "**Rank 606 -- project budget exceeded.**", and "Evaluation stops
    at the first violated rule, and only that rule's error is reported."  The same payload
    without a project is ordinary standalone work -- PRD SS3.3: "`project_id` is optional:
    standalone resident-maintenance work that is not part of any project leaves it as the empty
    string", and "A new work order is created in `PENDING_DISPATCH` with `vendor_id` the empty
    string, `actual_cost_cents` 0, `completed_on` the empty string".  Its benchmark is the
    PRD's own interior-paint figure of "292176".

    Design: Corner/validations/rent_ready_project_rejects_further_work_orders
    """
    ctx = x.renovated_home(api)
    settled = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_fields(settled, status=PROJECT_RENT_READY)
    assert_money_group(
        settled, committed_cost_cents=300000, budget_remaining_cents=100000
    )

    failed(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.paint_id,
                work_type="TURN",
                quoted_cost_cents=290000,
                scheduled_start_date="2026-09-10",
                scheduled_end_date="2026-09-12",
                project_id=ctx.project_id,
            ),
            x.OPS,
        ),
        ERR_PROJECT_SCOPE_LOCKED,
    )
    unchanged = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_fields(unchanged, status=PROJECT_RENT_READY)
    assert_money_group(
        unchanged, committed_cost_cents=300000, budget_remaining_cents=100000
    )

    standalone = created(
        api.create_work_order(
            f.work_order_payload(
                ctx.home_id,
                ctx.paint_id,
                work_type="RESIDENT_MAINTENANCE",
                quoted_cost_cents=290000,
                scheduled_start_date="2026-09-10",
                scheduled_end_date="2026-09-12",
            ),
            x.OPS,
        )
    )
    assert_fields(standalone, status=WO_PENDING_DISPATCH)
    assert_absent_or_empty(standalone, "project_id")
    assert_absent_or_empty(standalone, "vendor_id")
    assert_money_group(
        standalone, benchmark_total_cents=292176, actual_cost_cents=0
    )
