"""Opening cycles, the route turnaround calendar, drop-run merges, cycle
cancellation and roll-forward into a later cycle."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cycle,
    assert_drop_run,
    build_catalog,
    canonical_world,
    create_volunteer_shift_payload,
    drop_run_version,
    get_success_data,
    open_cycle,
    open_drop_run,
    order_version,
    place_order,
    publish_item,
    salt_world,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]


def test_new_cycle_starts_open_with_exception_state_not_started(api):
    """PRD §3.3: "A new cycle starts in status `OPEN`, with `locked_at`,
    `received_at` and `exception_deadline_at` all null, and with
    `exception_state` initialised to `NOT_STARTED`."

    Design: Corner/state_machines/new_cycle_starts_open_with_exception_state_not_started
    """
    set_clock(api, "2026-05-05T00:00:00Z")
    cycle = validate_success(
        api.create_cycle(
            {
                "code": "CY-MAY",
                "opens_at": "2026-05-05T00:00:00Z",
                "cutoff_at": "2026-05-25T00:00:00Z",
            },
            ADMIN,
        ),
        201,
    )

    assert_cycle(cycle)
    assert cycle["status"] == "OPEN"
    assert cycle["exception_state"] == "NOT_STARTED"
    assert cycle["received_at"] is None
    assert cycle["exception_deadline_at"] is None
    assert cycle["locked_at"] is None
    assert cycle["version"] == 1


# ------------------------------------------------- route turnaround buffer --
def test_route_turnaround_buffer_rejects_a_second_cycle_inside_48_hours(api):
    """PRD §3.3: "Two cycles collide on a route when the new cycle's `opens_at`
    falls strictly before the other cycle's `cutoff_at` plus 48 hours and,
    symmetrically, the other cycle's `opens_at` falls strictly before the new
    cycle's `cutoff_at` plus 48 hours; a collision is refused with
    `ERR_ROUTE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_turnaround_buffer_rejects_a_second_cycle_inside_48_hours
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)
    open_drop_run(api, w)

    early = open_cycle(
        api,
        w,
        code="CY-JUN-EARLY",
        opens_at="2026-05-26T00:00:00Z",
        cutoff_at="2026-06-15T00:00:00Z",
    )

    validate_error(
        api.create_drop_run(
            {"cycle_id": early["id"], "drop_point_id": w.depot_b_id}, ADMIN
        ),
        ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT.value,
    )

    _, meta = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": early["id"]})
    )
    assert meta["total_count"] == 0, "no route run may be minted for the colliding cycle"


def test_route_turnaround_admits_a_cycle_exactly_48_hours_later(api):
    """PRD §2.7: "**Route turnaround.** A route may host a second cycle when the
    new cycle's `opens_at` is at or after the existing cycle's `cutoff_at` plus
    48 hours. Inclusive at exactly 48 hours of separation."
    PRD §3.3: "A truck needs 48 hours of turnaround, so two windows that merely
    abut are still a conflict; only a genuine 48-hour separation clears the
    rule."

    Design: Difficulty/resource_temporal_overlap/route_turnaround_buffer_rejects_a_second_cycle_inside_48_hours
    """
    w = build_catalog(api, items=())
    open_cycle(api, w)
    open_drop_run(api, w)

    ok_cycle = open_cycle(
        api,
        w,
        code="CY-JUN-OK",
        opens_at="2026-05-27T00:00:00Z",
        cutoff_at="2026-06-20T00:00:00Z",
    )

    drop_run = validate_success(
        api.create_drop_run(
            {"cycle_id": ok_cycle["id"], "drop_point_id": w.depot_b_id}, ADMIN
        ),
        201,
    )
    assert_drop_run(drop_run)
    assert drop_run["status"] == "OPEN"

    _, meta = validate_paginated(
        api.list_route_runs(ADMIN, params={"route_id": w.route_id})
    )
    assert meta["total_count"] == 2


# ------------------------------------------------------------------ merge --
def test_merging_a_drop_run_repoints_its_orders_and_reflows_the_route_aggregate(api):
    """PRD §3.3: "First, the source moves `OPEN → MERGED`, its
    `merged_into_drop_run_id` is set to the target and its own `subtotal_cents`
    is zeroed. Second, because the source has emptied, every member order that
    pointed at it is repointed to the target drop run. Third, because the target
    has gained those orders, the target's `subtotal_cents` and
    `discounted_subtotal_cents` are recomputed. Fourth, because the target's
    subtotal moved, the route run's `aggregated_subtotal_cents` is recomputed."

    Design: Corner/state_machines/merging_a_drop_run_repoints_its_orders_and_reflows_the_route_aggregate
    """
    w = build_catalog(api, items=("salt",), include_ben=False)
    open_cycle(api, w)
    source = open_drop_run(api, w, drop_point_id=w.depot_a_id)
    target = open_drop_run(api, w, drop_point_id=w.depot_b_id)
    placed = place_order(api, w, w.mara_id, source["id"], [("salt", 5)])

    rows, _ = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": w.cycle_id})
    )
    route_run_id = rows[0]["id"]

    merged = validate_success(
        api.merge_drop_run(
            source["id"],
            {
                "target_drop_run_id": target["id"],
                "expected_drop_run_version": drop_run_version(api, w, source["id"]),
            },
            ADMIN,
        )
    )
    assert merged["status"] == "MERGED"
    assert merged["merged_into_drop_run_id"] == target["id"]
    assert merged["subtotal_cents"] == 0

    order = validate_success(api.get_member_order(placed["order"]["id"], ADMIN))
    assert order["drop_run_id"] == target["id"]

    target_after = validate_success(api.get_drop_run(target["id"], ADMIN))
    assert target_after["subtotal_cents"] == 5250

    route_run = validate_success(api.get_route_run(route_run_id, ADMIN))
    assert route_run["aggregated_subtotal_cents"] == 5250

    _, meta = validate_paginated(
        api.list_drop_runs(ADMIN, params={"merged_into_drop_run_id": target["id"]})
    )
    assert meta["total_count"] == 1


def test_merge_target_on_a_different_route_run_returns_merge_target_invalid(api):
    """PRD §2.9: "**Rung 40** — `target_drop_run_id` names a drop run other than
    this one, sitting on the same `route_run_id`, whose status is `OPEN`. Applies
    to merging a drop run. Failure: `ERR_MERGE_TARGET_INVALID`, HTTP 422."

    Design: Corner/state_machines/merge_target_on_a_different_route_run_returns_merge_target_invalid
    """
    w = build_catalog(api, items=())
    south = get_success_data(
        api.create_route(
            {
                "code": "R-SOUTH",
                "name": "South Route",
                "reefer_slots": 0,
                "route_minimum_cents": 1000,
                "max_pallets": 12,
            },
            ADMIN,
        )
    )
    dry_depot = get_success_data(
        api.create_drop_point(
            {"route_id": south["id"], "name": "Dry Depot", "drop_minimum_cents": 1000},
            ADMIN,
        )
    )
    open_cycle(api, w)
    source = open_drop_run(api, w, drop_point_id=w.depot_b_id)
    elsewhere = open_drop_run(api, w, drop_point_id=dry_depot["id"])

    validate_error(
        api.merge_drop_run(
            source["id"],
            {
                "target_drop_run_id": elsewhere["id"],
                "expected_drop_run_version": drop_run_version(api, w, source["id"]),
            },
            ADMIN,
        ),
        ApiErrorId.ERR_MERGE_TARGET_INVALID.value,
    )

    unchanged = validate_success(api.get_drop_run(source["id"], ADMIN))
    assert unchanged["status"] == "OPEN"
    assert unchanged["merged_into_drop_run_id"] is None


def test_logging_a_shift_on_a_merged_drop_run_returns_invalid_drop_run_state(api):
    """PRD §3.9: "Logging is permitted while the drop run's status is `OPEN`,
    `QUALIFIED`, `SUBMITTED`, `RECEIVED` or `SETTLED`, and is refused with
    `ERR_INVALID_DROP_RUN_STATE` in any other state."

    Design: Corner/state_machines/logging_a_shift_on_a_merged_drop_run_returns_invalid_drop_run_state
    """
    w = build_catalog(api, items=("salt",), include_ben=False)
    open_cycle(api, w)
    source = open_drop_run(api, w, drop_point_id=w.depot_a_id)
    target = open_drop_run(api, w, drop_point_id=w.depot_b_id)
    place_order(api, w, w.mara_id, source["id"], [("salt", 5)])
    get_success_data(
        api.merge_drop_run(
            source["id"],
            {
                "target_drop_run_id": target["id"],
                "expected_drop_run_version": drop_run_version(api, w, source["id"]),
            },
            ADMIN,
        )
    )

    validate_error(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(source["id"], w.mara_id, 4.0), ADMIN
        ),
        ApiErrorId.ERR_INVALID_DROP_RUN_STATE.value,
    )

    merged = validate_success(api.get_drop_run(source["id"], ADMIN))
    assert merged["status"] == "MERGED"
    _, meta = validate_paginated(
        api.list_volunteer_shifts(ADMIN, params={"drop_run_id": source["id"]})
    )
    assert meta["total_count"] == 0


# -------------------------------------------------------------- cancelling --
def test_cancelling_an_open_cycle_unwinds_orders_lines_and_route_runs(api):
    """PRD §3.5: "The cycle moves to `CANCELLED`. Every route run on it moves to
    `DEFERRED` — from `PLANNED → DEFERRED` on the open path, and from either
    `PLANNED → DEFERRED` or `QUALIFIED → DEFERRED` on the locked path. Every drop
    run whose status is `OPEN` or `QUALIFIED` moves to `CANCELLED`. Every member
    order whose status is `DRAFT`, `SUBMITTED` or `LOCKED` moves to `CANCELLED`,
    and every line on those orders whose status is `REQUESTED` or `CONFIRMED`
    moves to `CANCELLED`."

    Design: Corner/state_machines/cancelling_an_open_cycle_unwinds_orders_lines_and_authorizations
    """
    w = salt_world(api)
    rows, _ = validate_paginated(
        api.list_route_runs(ADMIN, params={"cycle_id": w.cycle_id})
    )
    route_run_id = rows[0]["id"]

    cycle = validate_success(api.cancel_cycle(w.cycle_id, ADMIN))
    assert cycle["status"] == "CANCELLED"

    assert validate_success(api.get_route_run(route_run_id, ADMIN))["status"] == "DEFERRED"
    assert validate_success(api.get_drop_run(w.drop_run_id, ADMIN))["status"] == "CANCELLED"
    assert validate_success(api.get_member_order(w.order_mara, ADMIN))["status"] == "CANCELLED"
    assert (
        validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))["status"]
        == "CANCELLED"
    )

    _, meta = validate_paginated(
        api.list_payments(ADMIN, params={"member_order_id": w.order_mara})
    )
    assert meta["total_count"] == 0


# ----------------------------------------------------------- roll forward --
def test_roll_forward_recreates_the_opted_in_lines_in_the_next_cycle(api):
    """PRD §3.5: "Second, because the run rolled, a new drop run with status
    `OPEN` is created on the target cycle for the same drop point, attaching to
    the target cycle's route run for that drop point's route, or minting one if
    the target cycle has none yet; the new drop run **inherits**
    `rollforward_count` from the source rather than starting at 0, so a chain of
    deferrals can be rolled forward only once in total and never repeatedly."
    PRD §3.5: "Fourth, because those orders exist, one new order line with status
    `REQUESTED` is created for each such line, with `rolled_from_order_line_id`
    pointing at the line it came from."

    Design: Corner/state_machines/roll_forward_recreates_the_opted_in_lines_in_the_next_cycle
    """
    w = salt_world(api, route_minimum_cents=100000, rollover_opt_in=True)
    target_cycle = open_cycle(
        api,
        w,
        code="CY-JUN",
        opens_at="2026-05-27T00:00:00Z",
        cutoff_at="2026-06-20T00:00:00Z",
    )
    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))

    rolled = validate_success(
        api.roll_forward_drop_run(
            w.drop_run_id, {"target_cycle_id": target_cycle["id"]}, ADMIN
        )
    )
    assert rolled["status"] == "ROLLED_FORWARD"
    assert rolled["rollforward_count"] == 1

    source_line = validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))
    assert source_line["status"] == "ROLLED_FORWARD"

    next_runs, _ = validate_paginated(
        api.list_drop_runs(ADMIN, params={"cycle_id": target_cycle["id"]})
    )
    assert len(next_runs) == 1
    assert next_runs[0]["status"] == "OPEN"
    assert next_runs[0]["cycle_id"] == target_cycle["id"]
    assert next_runs[0]["rollforward_count"] == 1

    new_lines, _ = validate_paginated(
        api.list_order_lines(
            ADMIN, params={"rolled_from_order_line_id": w.lines["mara_salt"]}
        )
    )
    assert len(new_lines) == 1
    assert new_lines[0]["status"] == "REQUESTED"
    assert new_lines[0]["qty_units"] == 5
    assert new_lines[0]["rolled_from_order_line_id"] == w.lines["mara_salt"]
    assert new_lines[0]["bound_case_price_cents"] == 0

    next_orders, meta = validate_paginated(
        api.list_member_orders(ADMIN, params={"drop_run_id": next_runs[0]["id"]})
    )
    assert meta["total_count"] == 1
    assert next_orders[0]["status"] == "DRAFT"


def test_roll_forward_to_a_cycle_that_is_not_open_returns_rollforward_limit(api):
    """PRD §3.5: "Rolling forward requires that the drop run has status
    `DEFERRED`, that the acting member is its `coordinator_member_id` with a
    `tier_rank` of at least 2, that the drop run's `rollforward_count` is still
    below 1, and that the supplied `target_cycle_id` names a cycle with status
    `OPEN` whose `cutoff_at` is strictly after the source cycle's `cutoff_at`. A
    violation of either the count limit or the target-cycle condition is refused
    with `ERR_ROLLFORWARD_LIMIT`."

    Design: Corner/state_machines/roll_forward_to_a_cycle_that_is_not_open_returns_rollforward_limit
    """
    w = salt_world(api, route_minimum_cents=100000, rollover_opt_in=True)
    set_clock(api, "2026-05-25T00:00:00Z")
    get_success_data(api.lock_cycle(w.cycle_id, ADMIN))

    validate_error(
        api.roll_forward_drop_run(w.drop_run_id, {"target_cycle_id": w.cycle_id}, ADMIN),
        ApiErrorId.ERR_ROLLFORWARD_LIMIT.value,
    )

    drop_run = validate_success(api.get_drop_run(w.drop_run_id, ADMIN))
    assert drop_run["status"] == "DEFERRED"
    assert drop_run["rollforward_count"] == 0
