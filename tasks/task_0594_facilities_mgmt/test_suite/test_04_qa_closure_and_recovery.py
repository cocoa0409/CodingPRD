"""Quality assurance, closure and recovery: the rework loop that walks a work order
backwards, the healing effects of a PASS on the physical world, the parallel billing
dimension, and the terminal lockdown of a closed order.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_asset,
    assert_dispatch,
    assert_pm_plan,
    assert_work_order,
    complete_dispatch,
    create_asset,
    create_building,
    create_pm_plan,
    create_vendor,
    create_work_order,
    dispatch_work_order,
    accept_dispatch,
    is_iso8601_timestamp,
    qa_work_order,
    read_dispatch,
    read_pm_plan,
    read_work_order,
    set_clock,
    setup_closed_work_order,
    setup_work_order_pending_qa,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]


# ---------------------------------------------------------------------------
# The rework loop
# ---------------------------------------------------------------------------
def test_qa_fail_walks_the_order_back_and_reopens_the_dispatch(api):
    """PRD §3.6: "A `FAIL` is a rework loop. The work order moves
    `PENDING_QA → IN_PROGRESS`, its `failed_qa_count` rises by 1, and the `COMPLETED`
    dispatch behind it moves `COMPLETED → ACCEPTED` so the vendor can go back and fix
    the work."
    PRD §3.6: "That dispatch's `completed_at`, `resolve_minutes`, `sla_resolve_met`, and
    `penalty_pct` are all cleared, and the work order's `billable_amount` is reset to
    unset."

    Design: Difficulty/non_linear_state_machine/work_order_qa_fail_rework_cycle_returns_dispatch_to_accepted
    """
    ctx = setup_work_order_pending_qa(
        clock="2026-05-04T09:00:00Z",
        complete_clock="2026-05-04T10:00:00Z",
        actual_labor_hours=2, actual_parts_cost=100.00,
        wo_overrides={"priority": "P3", "estimated_labor_hours": 2,
                      "estimated_parts_cost": 100.00},
    )
    assert ctx["work_order"]["billable_amount"] is not None

    work_order = validate_success(
        api.qa_work_order(ctx["work_order"]["id"], {"outcome": "FAIL"}, FM)
    )
    assert_work_order(work_order)
    assert work_order["status"] == "IN_PROGRESS"
    assert work_order["failed_qa_count"] == 1
    assert work_order["billable_amount"] is None

    dispatch = read_dispatch(ctx["dispatch"]["id"])
    assert_dispatch(dispatch)
    assert dispatch["status"] == "ACCEPTED"
    assert dispatch["completed_at"] is None
    assert dispatch["resolve_minutes"] is None
    assert dispatch["sla_resolve_met"] is None
    assert dispatch["penalty_pct"] == pytest.approx(0, abs=0.001)


def test_reworked_dispatch_completes_again_with_failed_qa_count_retained(api):
    """PRD §3.6: "Because the dispatch has left the completed set, and because the
    order's `failed_qa_count` is now permanently non-zero, both of the vendor's
    performance scores are recomputed — and when the dispatch completes a second time it
    will contribute nothing to the QA component of either score."
    PRD §3.5: "**Completion** is where the system's deepest cascade fires. The
    `VendorTech` reports its `actual_labor_hours` and `actual_parts_cost`; the dispatch
    moves `ACCEPTED → COMPLETED` and the work order `IN_PROGRESS → PENDING_QA`."
    PRD §3.4: "The **final settlement** variant runs only when a dispatch completes. It
    uses the vendor-reported `actual_labor_hours` and `actual_parts_cost` as its hours
    and parts, always uses the vendor's `hourly_rate`, and then continues past the gross:
    the penalty is the gross multiplied by the dispatch's `penalty_pct`, rounded half up
    to 2 decimal places, and the order's `billable_amount` is the gross less that
    penalty, again rounded half up to 2 decimal places."

    Design: Difficulty/non_linear_state_machine/work_order_qa_fail_rework_cycle_returns_dispatch_to_accepted
    """
    ctx = setup_work_order_pending_qa(
        clock="2026-05-04T09:00:00Z",
        complete_clock="2026-05-04T10:00:00Z",
        actual_labor_hours=2, actual_parts_cost=100.00,
        wo_overrides={"priority": "P3", "estimated_labor_hours": 2,
                      "estimated_parts_cost": 100.00},
    )
    qa_work_order(ctx["work_order"]["id"], "FAIL")

    complete_dispatch(ctx["dispatch"]["id"], ctx["vendor"]["id"],
                      actual_labor_hours=3, actual_parts_cost=100.00)

    work_order = read_work_order(ctx["work_order"]["id"])
    assert work_order["status"] == "PENDING_QA"
    assert work_order["failed_qa_count"] == 1, "the failed-QA count is permanent"
    # Re-settled on the second set of actuals, still priced off the 09:00 dispatched_at:
    # 3h * 100.00 = 300.00 labour, no P3 surcharge, 100.00 * 1.15 = 115.00 parts.
    assert work_order["billable_amount"] == pytest.approx(415.00, abs=0.01)


# ---------------------------------------------------------------------------
# QA legality and terminal lockdown
# ---------------------------------------------------------------------------
def test_qa_on_a_new_order_is_refused(api):
    """PRD §3.6: "A `FacilityManager` reviews the work and submits an `outcome` of
    either `PASS` or `FAIL`; a review submitted against an order that is not in
    `PENDING_QA` is refused with `ERR_WORK_ORDER_NOT_OPEN`."

    Design: Corner/state_machines/qa_on_new_work_order_rejected_as_not_open
    """
    building = create_building()
    work_order = create_work_order(building["id"], wo_type="CORRECTIVE", priority="P3",
                                   estimated_labor_hours=1, estimated_parts_cost=0)

    response = api.qa_work_order(work_order["id"], {"outcome": "PASS"}, FM)
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_NOT_OPEN.value)
    assert response.status_code == 409

    reread = read_work_order(work_order["id"])
    assert reread["status"] == "NEW"
    assert reread["closed_at"] is None


def test_cancelling_a_closed_order_is_refused(api):
    """PRD §3.6: "A `FacilityManager` may cancel an order that is in `NEW` or in
    `DISPATCHED`, moving it to `CANCELLED`; an order in any other status — an
    `IN_PROGRESS` order in particular — cannot be cancelled and the attempt is refused
    with `ERR_WORK_ORDER_NOT_OPEN`."
    PRD §3.6: "A `PASS` closes the order. Its `status` moves `PENDING_QA → CLOSED` and
    `closed_at` is stamped from the logical clock."
    PRD §3.6: "an order whose `chargeable` flag is false moves `billing_status`
    `PENDING → WAIVED` and is permanently excluded from every statement's O&M share ever
    after; an order whose `chargeable` flag is true stays at `PENDING`, waiting to be
    collected by a chargeback statement."

    Design: Corner/state_machines/cancel_closed_work_order_rejected_terminal_lockdown
    """
    ctx = setup_closed_work_order(
        clock="2026-05-04T09:00:00Z", complete_clock="2026-05-04T10:00:00Z",
        actual_labor_hours=2, actual_parts_cost=0,
        wo_overrides={"priority": "P3", "estimated_labor_hours": 2,
                      "estimated_parts_cost": 0},
    )

    response = api.cancel_work_order(ctx["work_order"]["id"], FM)
    validate_error(response, ApiErrorId.ERR_WORK_ORDER_NOT_OPEN.value)
    assert response.status_code == 409

    work_order = read_work_order(ctx["work_order"]["id"])
    assert work_order["status"] == "CLOSED"
    assert work_order["billing_status"] == "PENDING", (
        "a chargeable order waits at PENDING to be collected by a statement"
    )
    # 2h * 100.00 = 200.00, no P3 surcharge, no parts, no SLA penalty.
    assert work_order["billable_amount"] == pytest.approx(200.00, abs=0.01)
    assert is_iso8601_timestamp(work_order["closed_at"])
    assert work_order["closed_at"].startswith("2026-05-04T10:00:00"), (
        "closed_at is stamped from the logical clock at the moment QA passed"
    )


# ---------------------------------------------------------------------------
# A PASS heals the physical world
# ---------------------------------------------------------------------------
def test_preventive_close_resets_asset_counters_and_advances_the_plan(api):
    """PRD §3.6: "If the order was `PREVENTIVE` and named an asset, the asset's
    `runtime_hours` is reset to 0, its `failure_count` is decremented by 1 but never
    below 0, its `last_pm_at` is stamped from the clock, and its `condition_score` is
    recomputed on the restarted decay curve; and if the order also named a `pm_plan_id`,
    that plan's `next_due_at` is pushed forward by its own `interval_days` days."
    PRD §3.6: "A `PASS` closes the order. Its `status` moves `PENDING_QA → CLOSED` and
    `closed_at` is stamped from the logical clock."

    Design: Corner/state_machines/preventive_close_resets_asset_counters_and_advances_plan
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building()
    asset = create_asset(building["id"], asset_tag="AHU-01", category="HVAC",
                         criticality="STANDARD", runtime_hours=3000)
    plan = create_pm_plan(asset["id"], interval_days=30, grace_days=5,
                          next_due_at="2026-06-01T00:00:00Z")
    vendor = create_vendor()
    work_order = create_work_order(
        building["id"], asset_id=asset["id"], pm_plan_id=plan["id"],
        wo_type="PREVENTIVE", priority="P2", estimated_labor_hours=3,
        estimated_parts_cost=200.00,
    )
    dispatch = dispatch_work_order(work_order["id"], vendor["id"])
    accept_dispatch(dispatch["id"], vendor["id"])
    set_clock("2026-05-04T11:00:00Z")
    complete_dispatch(dispatch["id"], vendor["id"], actual_labor_hours=3,
                      actual_parts_cost=200.00)

    closed = validate_success(
        api.qa_work_order(work_order["id"], {"outcome": "PASS"}, FM)
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"].startswith("2026-05-04T11:00:00")
    # 3h * 100.00 = 300.00 labour, + 10% P2 = 30.00, + 200.00 * 1.15 = 230.00 parts.
    assert closed["billable_amount"] == pytest.approx(560.00, abs=0.01)

    healed = validate_success(api.get_asset(asset["id"], FM))
    assert_asset(healed)
    assert healed["runtime_hours"] == pytest.approx(0, abs=0.01)
    assert healed["failure_count"] == 0, "decremented by 1 but never below 0"
    assert healed["condition_score"] == pytest.approx(100.00, abs=0.01), (
        "the decay curve restarts from a zeroed runtime"
    )
    assert healed["last_pm_at"].startswith("2026-05-04T11:00:00")

    advanced = read_pm_plan(asset["id"], plan["id"])
    assert_pm_plan(advanced)
    assert advanced["next_due_at"].startswith("2026-07-01T00:00:00"), (
        "next_due_at is pushed forward by the plan's own interval_days of 30"
    )
    assert advanced["status"] == "ACTIVE"


def test_closing_a_non_chargeable_order_waives_the_billing_dimension(api):
    """PRD §3.6: "On the billing dimension, an order whose `chargeable` flag is false
    moves `billing_status` `PENDING → WAIVED` and is permanently excluded from every
    statement's O&M share ever after; an order whose `chargeable` flag is true stays at
    `PENDING`, waiting to be collected by a chargeback statement."
    PRD §3.4: "A work order is the unit of work in the system, and it carries two
    independent status dimensions on the same row: an execution dimension in `status`
    and a billing dimension in `billing_status`. The two advance separately and neither
    waits for the other."

    Design: Corner/state_machines/non_chargeable_order_close_waives_billing_dimension
    """
    ctx = setup_work_order_pending_qa(
        clock="2026-05-04T09:00:00Z", complete_clock="2026-05-04T10:00:00Z",
        actual_labor_hours=2, actual_parts_cost=0,
        wo_overrides={"priority": "P3", "estimated_labor_hours": 2,
                      "estimated_parts_cost": 0, "chargeable": False},
    )

    closed = validate_success(
        api.qa_work_order(ctx["work_order"]["id"], {"outcome": "PASS"}, FM)
    )
    assert_work_order(closed)
    assert closed["status"] == "CLOSED"
    assert closed["billing_status"] == "WAIVED"
    assert closed["statement_id"] is None

    _, meta = validate_paginated(
        api.list_work_orders(FM, params={"billing_status": "WAIVED"})
    )
    assert meta["total_count"] == 1
