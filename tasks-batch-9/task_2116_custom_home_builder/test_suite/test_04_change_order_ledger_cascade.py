"""Approving, capping and voiding a change order: the four-link cascade and its mirror."""

from test_helpers import (
    assert_instant_equals,
    assert_money_equals,
    assert_project_ledger_invariants,
    read_allowance_item,
    read_change_order,
    read_contract_position,
    read_project,
    read_schedule_task,
    setup_approved_change_order,
    setup_job,
    setup_submitted_change_order,
    validate_success,
)


def test_change_order_approval_drives_contract_sum_over_the_gmp_cap(api):
    """PRD §3.3: "**Approval** advances `SUBMITTED → APPROVED`, requires the project to be
    `UNDER_CONSTRUCTION`, stamps `decided_at`, and sets off a four-link cascade: the change
    order's `priced_amount` joins `approved_change_order_total`, which forces
    `contract_sum_current` to be recomputed; because `contract_sum_current` moved,
    `budget_posture` is re-evaluated and may become `OVER_GMP`; because the posture became
    `OVER_GMP`, every allowance item on the project currently in `OPEN` cascades `OPEN →
    FROZEN`; and the project's `version` is incremented by one."
    PRD §3.5: "It also reports `gmp_headroom`, which is the `gmp_cap` minus
    `contract_sum_current` rounded half up to two decimals when a cap exists, and null when the
    project carries no cap."

    Design: Difficulty/transitive_cascade/co_approval_cascades_to_allowance_freeze
    """
    ctx = setup_job(gmp_cap=950000.00)
    change_order = setup_submitted_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )

    approved = validate_success(
        api.decide_change_order(
            change_order["id"], {"decision": "APPROVE"}, ctx["client_headers"]
        ),
        200,
    )

    assert approved["status"] == "APPROVED"
    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["approved_change_order_total"], 50315.50, "approved_change_order_total"
    )
    assert_money_equals(project["contract_sum_current"], 950315.50, "contract_sum_current")
    assert project["budget_posture"] == "OVER_GMP"
    assert_project_ledger_invariants(project)

    position = read_contract_position(ctx["project"]["id"])
    assert_money_equals(position["gmp_headroom"], -315.50, "gmp_headroom")


def test_over_gmp_posture_freezes_every_open_allowance_line(api):
    """PRD §2.6: "When a recomputation moves the posture *into* `OVER_GMP`, every allowance
    item on that project that is currently `OPEN` cascades to `FROZEN`, has its `frozen_at`
    stamped with the logical clock now, and has its `version` incremented."
    PRD §2.6: "First: if the project carries a `gmp_cap` and `contract_sum_current` is
    **strictly greater than** that cap, the posture is `OVER_GMP`; a `contract_sum_current`
    exactly equal to `gmp_cap` is *not* over the cap."

    Design: Difficulty/transitive_cascade/co_approval_cascades_to_allowance_freeze
    """
    ctx = setup_job(gmp_cap=950000.00)
    line_before = read_allowance_item(ctx["allowance_item"]["id"])
    assert line_before["status"] == "OPEN"
    assert line_before["frozen_at"] is None

    setup_approved_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )

    line_after = read_allowance_item(ctx["allowance_item"]["id"])
    assert line_after["status"] == "FROZEN"
    assert line_after["frozen_at"] is not None
    assert read_project(ctx["project"]["id"])["budget_posture"] == "OVER_GMP"


def test_contract_sum_exactly_on_the_gmp_cap_is_not_over_the_cap(api):
    """PRD §2.6: "First: if the project carries a `gmp_cap` and `contract_sum_current` is
    **strictly greater than** that cap, the posture is `OVER_GMP`; a `contract_sum_current`
    exactly equal to `gmp_cap` is *not* over the cap."
    PRD §3.5: "It also reports `gmp_headroom`, which is the `gmp_cap` minus
    `contract_sum_current` rounded half up to two decimals when a cap exists, and null when the
    project carries no cap."

    Design: Difficulty/boundary_precision_check/contract_sum_exactly_equal_to_gmp_cap_is_not_over
    """
    ctx = setup_job(gmp_cap=950315.50)
    change_order = setup_submitted_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )

    validate_success(
        api.decide_change_order(
            change_order["id"], {"decision": "APPROVE"}, ctx["client_headers"]
        ),
        200,
    )

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["contract_sum_current"], 950315.50, "contract_sum_current")
    assert project["budget_posture"] == "WITHIN_BUDGET", (
        "a contract sum exactly equal to the cap is not over it"
    )

    position = read_contract_position(ctx["project"]["id"])
    assert_money_equals(position["gmp_headroom"], 0.00, "gmp_headroom")


def test_contract_sum_exactly_on_the_gmp_cap_leaves_allowance_lines_open(api):
    """PRD §2.6: "When a recomputation moves the posture *into* `OVER_GMP`, every allowance
    item on that project that is currently `OPEN` cascades to `FROZEN`, has its `frozen_at`
    stamped with the logical clock now, and has its `version` incremented."
    PRD §2.6: "First: if the project carries a `gmp_cap` and `contract_sum_current` is
    **strictly greater than** that cap, the posture is `OVER_GMP`; a `contract_sum_current`
    exactly equal to `gmp_cap` is *not* over the cap."

    Design: Difficulty/boundary_precision_check/contract_sum_exactly_equal_to_gmp_cap_is_not_over
    """
    ctx = setup_job(gmp_cap=950315.50)
    setup_approved_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )

    line = read_allowance_item(ctx["allowance_item"]["id"])
    assert line["status"] == "OPEN", "no freeze fires while the posture stays WITHIN_BUDGET"
    assert line["frozen_at"] is None


def test_voiding_an_approved_change_order_restores_the_contract_sum(api):
    """PRD §3.3: "The void is the exact compensating mirror of the approval: the change
    order's `priced_amount` is removed from `approved_change_order_total`, which forces
    `contract_sum_current` to be recomputed; `budget_posture` is re-evaluated and may leave
    `OVER_GMP`; if it did leave `OVER_GMP`, every allowance item on the project currently in
    `FROZEN` cascades `FROZEN → OPEN`; and the project's `version` is incremented by one."
    PRD §2.6: "`contract_sum_current` is `base_contract_amount` plus
    `approved_change_order_total` plus `allowance_variance_total`, rounded half up to two
    decimal places."

    Design: Difficulty/compensating_invariant/change_order_void_restores_contract_sum_exactly
    """
    ctx = setup_job(gmp_cap=950000.00)
    change_order = setup_approved_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )
    assert read_project(ctx["project"]["id"])["budget_posture"] == "OVER_GMP"

    voided = validate_success(
        api.void_change_order(
            change_order["id"],
            {"void_reason": "Client descoped the screened porch"},
            ctx["client_headers"],
        ),
        200,
    )

    assert voided["status"] == "VOIDED"
    project = read_project(ctx["project"]["id"])
    assert_money_equals(
        project["approved_change_order_total"], 0.00, "approved_change_order_total"
    )
    assert_money_equals(project["contract_sum_current"], 900000.00, "contract_sum_current")
    assert project["budget_posture"] == "WITHIN_BUDGET"
    assert_project_ledger_invariants(project)


def test_voiding_an_approved_change_order_thaws_allowances_and_unwinds_the_schedule(api):
    """PRD §2.6: "When a later recomputation moves the posture *out of* `OVER_GMP`, every
    allowance item on that project that is currently `FROZEN` cascades back to `OPEN`, has its
    `frozen_at` cleared to null, and has its `version` incremented again."
    PRD §3.3: "If the voided change order carried a `schedule_impact_days` greater than zero,
    every schedule task on the project still in `PLANNED` or `RELEASED` has its `planned_start`
    and `planned_finish` pulled earlier by exactly that many days."

    Design: Difficulty/compensating_invariant/change_order_void_restores_contract_sum_exactly
    """
    ctx = setup_job(gmp_cap=950000.00)
    change_order = setup_approved_change_order(
        ctx,
        origin="CLIENT_REQUEST",
        scope_description="Add a screened porch",
        direct_cost=40000.00,
        schedule_impact_days=10,
    )
    assert read_allowance_item(ctx["allowance_item"]["id"])["status"] == "FROZEN"

    validate_success(
        api.void_change_order(
            change_order["id"],
            {"void_reason": "Client descoped the screened porch"},
            ctx["client_headers"],
        ),
        200,
    )

    line = read_allowance_item(ctx["allowance_item"]["id"])
    assert line["status"] == "OPEN"
    assert line["frozen_at"] is None

    task = read_schedule_task(ctx["task_frame"]["id"])
    assert_instant_equals(
        task["planned_start"], "2026-09-01T00:00:00.000Z", "planned_start after the void"
    )
    assert_instant_equals(
        task["planned_finish"], "2026-10-15T00:00:00.000Z", "planned_finish after the void"
    )
    assert read_change_order(change_order["id"])["status"] == "VOIDED"
