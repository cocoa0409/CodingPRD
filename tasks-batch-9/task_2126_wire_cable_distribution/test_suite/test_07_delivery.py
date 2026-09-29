"""Jobsite delivery: scheduling, truck occupancy, reel handling and dispatch."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    commit_cut,
    convert_quote,
    create_branch,
    create_delivery_run_payload,
    create_truck,
    build_quote,
    create_customer,
    create_product,
    issue_quote,
    list_runs,
    make_branch_ops_headers,
    make_driver_headers,
    publish_index,
    PRODUCT_P1,
    read_allocation,
    read_order,
    read_run,
    receive_reel,
    schedule_run,
    setup_allocated_order,
    setup_staged_order_by_cut,
    setup_staged_order_by_pick,
    validate_error,
    validate_success,
)

CUT_LINE = {"put_up": "CUT", "requested_length_ft": 300}
MASTER_LINE = {"put_up": "MASTER_REEL", "requested_length_ft": 2500}


# ══════════════════════════════════════════════════════════════════════════
# Dispatch is gated on the order having reached STAGED
# ══════════════════════════════════════════════════════════════════════════

def _run_scheduled_for_a_half_committed_order():
    """A two-line CUT order fully allocated from one 1000 ft reel, of which
    only the first allocation has been cut, so the order is still ALLOCATED."""
    scn = setup_allocated_order(
        [CUT_LINE, dict(CUT_LINE)],
        reels=[{"nominal_length_ft": 1000}],
        truck_overrides={"truck_code": "T-1"},
    )
    commit_cut(
        scn["allocations"][0]["id"], scn["branch"]["id"],
        "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z",
    )
    scn["run"] = schedule_run(
        scn["order"]["id"], scn["truck"]["id"], scn["branch"]["id"],
        "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z",
    )
    return scn


def test_dispatch_is_refused_while_the_order_is_only_allocated(api):
    """PRD §3.8: "The run must be `SCHEDULED`, otherwise
    `ERR_RUN_INVALID_STATE`, and the order behind it must have reached
    `STAGED`, otherwise `ERR_ORDER_NOT_STAGED` — the truck does not leave
    until every allocation is committed."
    PRD §3.7: "When the commit that just happened was the last one — that is,
    when every allocation on the order has reached `COMMITTED` — the order
    bubbles up `ALLOCATED → STAGED` on its fulfilment axis, and the goods are
    ready for a truck."

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_sales_order_reaching_staged
    """
    scn = _run_scheduled_for_a_half_committed_order()

    response = api.dispatch_delivery_run(
        scn["run"]["id"], make_driver_headers(scn["truck"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_ORDER_NOT_STAGED.value)
    assert read_run(scn["run"]["id"])["status"] == "SCHEDULED"
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "ALLOCATED"


def test_an_all_cut_order_derives_tailgate_handling_and_no_reel_weight(api):
    """PRD §3.8: "`heaviest_reel_lbs` is the greatest `reel_weight_lbs` among
    the parts of the order's allocations that are `COMMITTED` with
    `commit_mode` `PICK`; an all-cut order has no such allocation and its
    `heaviest_reel_lbs` is 0, because cut cable rides on disposable reels and
    never drives handling."
    PRD §3.8: "Otherwise, if `heaviest_reel_lbs` is strictly greater than 250
    pounds the method is `BOOM_LIFT`. Otherwise it is `TAILGATE`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_sales_order_reaching_staged
    """
    scn = _run_scheduled_for_a_half_committed_order()

    run = read_run(scn["run"]["id"])
    assert run["reel_handling"] == "TAILGATE"
    assert run["heaviest_reel_lbs"] == 0

    assert read_allocation(scn["allocations"][1]["id"])["status"] == "RESERVED"


# ══════════════════════════════════════════════════════════════════════════
# The truck's half-open window is exclusive, but adjacency is allowed
# ══════════════════════════════════════════════════════════════════════════

def _two_orders_one_truck():
    """Two separate single-line CUT orders out of one branch, one truck, and
    a first run occupying that truck from 08:00 to 10:00."""
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    truck = create_truck(branch["id"], truck_code="T-1")
    receive_reel(product["id"], branch["id"], 1000)
    orders = []
    for _ in range(2):
        quote, _ = build_quote(
            customer["id"], branch["id"], product["id"], [CUT_LINE]
        )
        issue_quote(quote["id"], issuer="rep-2")
        orders.append(convert_quote(quote["id"], issuer="rep-2"))
    first_run = schedule_run(
        orders[0]["id"], truck["id"], branch["id"],
        "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z",
    )
    return branch, truck, orders, first_run


def test_a_truck_window_overlapping_an_existing_run_is_rejected(api):
    """PRD §3.8: "Truck occupancy is deliberately the opposite of the cut
    floor: the requested window is half-open, running from `window_start`
    inclusive to `window_end` exclusive, and it conflicts with an existing run
    on the same truck when the requested start is strictly before that run's
    `window_end` and that run's `window_start` is strictly before the
    requested end."
    PRD §3.8: "A conflict is refused with `ERR_TRUCK_WINDOW_CONFLICT`, and a
    truck's occupancy is exclusive: capacity is one, not a configured count."

    Design: Difficulty/resource_temporal_overlap/truck_half_open_window_exclusive_with_adjacency_allowed
    """
    branch, truck, orders, _ = _two_orders_one_truck()

    response = api.create_delivery_run(
        create_delivery_run_payload(
            orders[1]["id"], truck["id"],
            "2026-08-10T09:00:00Z", "2026-08-10T11:00:00Z",
            jobsite_address="44 Turning Basin",
        ),
        make_branch_ops_headers(branch["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value)
    assert len(list_runs(truck_id=truck["id"])) == 1


def test_a_truck_window_starting_when_another_ends_is_accepted(api):
    """PRD §3.8: "Both comparisons are strict, so a run beginning at exactly
    the instant another ends is accepted."
    PRD §3.8: "The run copies its `branch_id` from the order and starts in
    `status` `SCHEDULED`, with `dispatched_at` and `delivered_at` null."
    PRD §3.8: "`heaviest_reel_lbs` is the greatest `reel_weight_lbs` among the
    parts of the order's allocations that are `COMMITTED` with `commit_mode`
    `PICK`; an all-cut order has no such allocation and its
    `heaviest_reel_lbs` is 0, because cut cable rides on disposable reels and
    never drives handling."

    Design: Difficulty/resource_temporal_overlap/truck_half_open_window_exclusive_with_adjacency_allowed
    """
    branch, truck, orders, _ = _two_orders_one_truck()

    response = api.create_delivery_run(
        create_delivery_run_payload(
            orders[1]["id"], truck["id"],
            "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z",
            jobsite_address="44 Turning Basin",
        ),
        make_branch_ops_headers(branch["id"]),
    )
    run = validate_success(response, 201)

    assert_same_instant(
        run["window_start"], "2026-08-10T10:00:00Z", "DeliveryRun.window_start"
    )
    assert run["status"] == "SCHEDULED"
    assert run["reel_handling"] == "TAILGATE"
    assert len(list_runs(truck_id=truck["id"])) == 2


# ══════════════════════════════════════════════════════════════════════════
# Admission order: the truck's branch is checked before the boom-lift rule
# ══════════════════════════════════════════════════════════════════════════

def _staged_master_order_and_a_foreign_flatbed():
    scn = setup_staged_order_by_pick(
        [MASTER_LINE], reels=[{"nominal_length_ft": 2500}]
    )
    other_branch = create_branch(name="Dallas DC")
    foreign_truck = create_truck(
        other_branch["id"], truck_code="T-DAL", has_boom_lift=False
    )
    return scn, foreign_truck


def test_truck_branch_mismatch_is_reported_before_the_boom_lift_rule(api):
    """PRD §2.7: "Checks are evaluated in the fixed order below; the first
    violated check determines the response, and no later check is evaluated.
    The lowest number wins."
    PRD §2.7: "Cross-entity references are mutually consistent: on
    delivery-run creation the truck's `branch_id` equals the order's
    `branch_id`, otherwise `ERR_TRUCK_BRANCH_MISMATCH`; every allocation's
    reel sits at the order's branch; and on a return the reel's
    `delivered_sales_order_id` equals the order line's `sales_order_id`,
    meaning the reel is one the order line actually shipped, otherwise
    `ERR_REEL_NOT_ON_ORDER_LINE`."
    PRD §2.7: "A run whose derived `reel_handling` is `BOOM_LIFT` is assigned
    a truck that carries one — otherwise `ERR_BOOM_LIFT_REQUIRED` (409), on
    delivery-run creation."

    Design: Difficulty/priority_pair_validation_conflict/truck_branch_mismatch_referential_beats_boom_lift_required_safety
    """
    scn, foreign_truck = _staged_master_order_and_a_foreign_flatbed()

    response = api.create_delivery_run(
        create_delivery_run_payload(
            scn["order"]["id"], foreign_truck["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z",
            jobsite_address="9 Ship Channel",
        ),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_TRUCK_BRANCH_MISMATCH.value)


def test_a_rejected_run_creation_persists_no_run_and_leaves_the_order_staged(api):
    """PRD §3.8: "Three admission rules guard the schedule. The truck must be
    domiciled at the order's branch, otherwise `ERR_TRUCK_BRANCH_MISMATCH`."
    PRD §3.7: "When the commit that just happened was the last one — that is,
    when every allocation on the order has reached `COMMITTED` — the order
    bubbles up `ALLOCATED → STAGED` on its fulfilment axis, and the goods are
    ready for a truck."

    Design: Difficulty/priority_pair_validation_conflict/truck_branch_mismatch_referential_beats_boom_lift_required_safety
    """
    scn, foreign_truck = _staged_master_order_and_a_foreign_flatbed()

    response = api.create_delivery_run(
        create_delivery_run_payload(
            scn["order"]["id"], foreign_truck["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z",
            jobsite_address="9 Ship Channel",
        ),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TRUCK_BRANCH_MISMATCH.value)

    assert list_runs(sales_order_id=scn["order"]["id"]) == []
    assert read_order(scn["order"]["id"])["fulfillment_status"] == "STAGED"


# ══════════════════════════════════════════════════════════════════════════
# Delivery-run corners
# ══════════════════════════════════════════════════════════════════════════

def test_completing_a_run_that_was_never_dispatched_is_rejected(api):
    """PRD §3.8: "The driver, again owning the truck, moves the run
    `DISPATCHED → DELIVERED` with no request body; a run in any other state
    yields `ERR_RUN_INVALID_STATE`."

    Design: Corner/state_machines/deliver_before_dispatch_returns_run_invalid_state
    """
    scn = setup_staged_order_by_cut(
        [CUT_LINE], reels=[{"nominal_length_ft": 1000}],
        truck_overrides={"truck_code": "T-1"},
    )
    run = schedule_run(
        scn["order"]["id"], scn["truck"]["id"], scn["branch"]["id"],
        "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z",
    )

    response = api.deliver_delivery_run(
        run["id"], make_driver_headers(scn["truck"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_RUN_INVALID_STATE.value)
    refreshed = read_run(run["id"])
    assert refreshed["status"] == "SCHEDULED"
    assert refreshed["delivered_at"] is None
    order = read_order(scn["order"]["id"])
    assert order["fulfillment_status"] == "STAGED"
    assert order["billing_status"] == "UNBILLED"


def test_a_second_run_for_an_order_with_an_open_run_is_rejected(api):
    """PRD §3.8: "The order must not already have a run in `SCHEDULED` or
    `DISPATCHED` status, otherwise `ERR_ORDER_HAS_ACTIVE_RUN` — a delivered
    run does not block a new one, but an open one does."

    Design: Corner/state_machines/second_delivery_run_for_the_same_order_returns_order_has_active_run
    """
    scn = setup_staged_order_by_cut(
        [CUT_LINE], reels=[{"nominal_length_ft": 1000}],
        truck_overrides={"truck_code": "T-1"},
    )
    first = schedule_run(
        scn["order"]["id"], scn["truck"]["id"], scn["branch"]["id"],
        "2026-08-03T08:00:00Z", "2026-08-03T10:00:00Z",
    )

    response = api.create_delivery_run(
        create_delivery_run_payload(
            scn["order"]["id"], scn["truck"]["id"],
            "2026-08-04T08:00:00Z", "2026-08-04T10:00:00Z",
        ),
        make_branch_ops_headers(scn["branch"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ORDER_HAS_ACTIVE_RUN.value)
    runs = list_runs(sales_order_id=scn["order"]["id"])
    assert len(runs) == 1
    assert read_run(first["id"])["status"] == "SCHEDULED"


def test_a_jobsite_forklift_overrides_the_boom_lift_requirement(api):
    """PRD §3.8: "If `jobsite_has_forklift` is true the method is `FORKLIFT`,
    and that branch wins outright — a site with its own forklift never demands
    a boom lift, however heavy the reel."
    PRD §3.8: "`heaviest_reel_lbs` is the greatest `reel_weight_lbs` among the
    parts of the order's allocations that are `COMMITTED` with `commit_mode`
    `PICK`; an all-cut order has no such allocation and its
    `heaviest_reel_lbs` is 0, because cut cable rides on disposable reels and
    never drives handling."
    PRD §3.8: "The run copies its `branch_id` from the order and starts in
    `status` `SCHEDULED`, with `dispatched_at` and `delivered_at` null."

    Design: Corner/calculations/jobsite_forklift_overrides_the_boom_lift_requirement
    """
    scn = setup_staged_order_by_pick(
        [MASTER_LINE], reels=[{"nominal_length_ft": 2500}],
        truck_overrides={"truck_code": "T-FLAT", "has_boom_lift": False},
    )

    response = api.create_delivery_run(
        create_delivery_run_payload(
            scn["order"]["id"], scn["truck"]["id"],
            "2026-08-02T08:00:00Z", "2026-08-02T10:00:00Z",
            jobsite_address="9 Ship Channel",
            jobsite_has_forklift=True,
        ),
        make_branch_ops_headers(scn["branch"]["id"]),
    )
    run = validate_success(response, 201)

    assert run["reel_handling"] == "FORKLIFT"
    assert run["heaviest_reel_lbs"] == pytest.approx(320.0, abs=0.05)
    assert run["status"] == "SCHEDULED"
    assert run["branch_id"] == scn["branch"]["id"]
