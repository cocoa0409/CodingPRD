"""Load building: assignment gating, capacity boundary, assign/unassign
weight conservation, optimistic concurrency, and cancel/unassign reverts
(PRD §2.9, §3.5, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_order,
    create_load,
    create_work_order,
    get_assignment,
    get_load,
    get_work_order,
    retreat_order_once,
    setup_failed_order,
    setup_shop,
    unassign_order,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
SCHED = TEST_USERS["shop_scheduler"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / assignment_gated_on_work_order_state
# ---------------------------------------------------------------------------

def test_assignment_gated_on_work_order_state(api):
    """PRD §3.5: "The order's `processing_status` must be `RECEIVED` or
    `AWAITING_RETREAT` (`ERR_WORK_ORDER_NOT_ASSIGNABLE`, HTTP 409), and the
    order's `recipe_id` must equal the load's `recipe_id`
    (`ERR_RECIPE_MISMATCH`, HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/assignment_gated_on_work_order_state
    """
    shop = setup_shop(qualified=False)
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load_a = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-02T08:00:00Z",
        scheduled_end_at="2026-08-02T12:00:00Z",
    )
    assign_order(load_a["id"], order["id"])
    assert get_work_order(order["id"])["processing_status"] == "SCHEDULED"

    load_b = create_load(
        shop["furnace"]["id"], shop["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    res = api.create_load_assignment(
        load_b["id"],
        {
            "work_order_id": order["id"],
            "expected_load_batch_version": get_load(load_b["id"])["version"],
        },
        SCHED,
    )
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_NOT_ASSIGNABLE.value)


def test_awaiting_retreat_order_is_assignable(api):
    """PRD §3.5: "The order's `processing_status` must be `RECEIVED` or
    `AWAITING_RETREAT` (`ERR_WORK_ORDER_NOT_ASSIGNABLE`, HTTP 409), and the
    order's `recipe_id` must equal the load's `recipe_id`
    (`ERR_RECIPE_MISMATCH`, HTTP 422)."
    PRD §3.7: "`RE_TREAT` is available only while the order's `retreat_count`
    remains strictly below the recipe's `max_retreats` — once the count has
    reached the cap, a re-treat attempt fails with `ERR_RETREAT_LIMIT_REACHED`
    (HTTP 422); a successful re-treat moves the order from `PROCESSED` to
    `AWAITING_RETREAT`, increments `retreat_count` by one, and resets
    `quality_status` from `FAILED` to `PENDING_TEST`, ready to be scheduled
    onto a new load."

    Design: Difficulty/cross_entity_state_dependency/assignment_gated_on_work_order_state
    """
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 2})
    order = retreat_order_once(bundle)
    assert order["processing_status"] == "AWAITING_RETREAT"

    load2 = create_load(
        bundle["shop"]["furnace"]["id"], bundle["shop"]["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    assignment = assign_order(load2["id"], order["id"])
    assert assignment["status"] == "ACTIVE"
    assert get_work_order(order["id"])["processing_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / load_weight_exactly_at_capacity_allowed
# ---------------------------------------------------------------------------

def test_load_weight_exactly_at_capacity_allowed(api):
    """PRD §3.5: "Capacity is enforced by weight: a load's `total_weight_lb`
    is the sum of `received_weight_lb` over its `ACTIVE` assignments, and an
    assignment that would push that total strictly above the furnace's
    `max_load_weight_lb` is rejected with `ERR_LOAD_WEIGHT_EXCEEDED` — a load
    landing exactly at the maximum is permitted."

    Design: Difficulty/boundary_precision_check/load_weight_exactly_at_capacity_allowed
    """
    shop = setup_shop(qualified=False)
    order_600 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=600
    )
    order_400 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=400
    )
    order_1 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"],
        part_quantity=1, received_weight_lb=1,
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])

    assign_order(load["id"], order_600["id"])
    assign_order(load["id"], order_400["id"])
    mid = get_load(load["id"])
    assert mid["total_weight_lb"] == 1000, (
        f"600 + 400 lands exactly at the 1000 lb maximum, got "
        f"{mid['total_weight_lb']}"
    )

    res = api.create_load_assignment(
        load["id"],
        {
            "work_order_id": order_1["id"],
            "expected_load_batch_version": mid["version"],
        },
        SCHED,
    )
    validate_error(res, ApiErrorId.ERR_LOAD_WEIGHT_EXCEEDED.value)


def test_load_weight_fractional_capacity_boundary(api):
    """PRD §3.5: "Capacity is enforced by weight: a load's `total_weight_lb`
    is the sum of `received_weight_lb` over its `ACTIVE` assignments, and an
    assignment that would push that total strictly above the furnace's
    `max_load_weight_lb` is rejected with `ERR_LOAD_WEIGHT_EXCEEDED` — a load
    landing exactly at the maximum is permitted."
    PRD §2.6: "Weights are tracked in pounds with up to three decimal places,
    which applies to both an order's `received_weight_lb` and a load's
    `total_weight_lb`."

    Design: Difficulty/boundary_precision_check/load_weight_exactly_at_capacity_allowed
    """
    shop = setup_shop(qualified=False)
    order_a = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=999.999
    )
    order_b = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=0.001
    )
    order_c = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=0.001
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])

    assign_order(load["id"], order_a["id"])
    assign_order(load["id"], order_b["id"])
    at_cap = get_load(load["id"])
    assert at_cap["total_weight_lb"] == 1000, (
        f"999.999 + 0.001 == 1000 must be permitted, got "
        f"{at_cap['total_weight_lb']}"
    )

    res = api.create_load_assignment(
        load["id"],
        {
            "work_order_id": order_c["id"],
            "expected_load_batch_version": at_cap["version"],
        },
        SCHED,
    )
    validate_error(res, ApiErrorId.ERR_LOAD_WEIGHT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / assign_unassign_restores_load_weight
# ---------------------------------------------------------------------------

def test_assign_unassign_restores_load_weight(api):
    """PRD §3.5: "A successful assignment is created `ACTIVE` with
    `assigned_at` stamped from the logical clock; the order advances from
    `RECEIVED` (or `AWAITING_RETREAT`) to `SCHEDULED`; the load's
    `total_weight_lb` is recomputed and its `version` increments by one."
    PRD §3.5: "It moves the assignment from `ACTIVE` to `REMOVED`, returns the
    order to `RECEIVED` when its `retreat_count` is 0 or to
    `AWAITING_RETREAT` when the lot has already been re-treated at least once,
    recomputes the load's `total_weight_lb`, and bumps the load's `version`."

    Design: Difficulty/compensating_invariant/assign_unassign_restores_load_weight
    """
    shop = setup_shop(qualified=False)
    order = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=400
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    v0 = get_load(load["id"])["version"]
    assert get_load(load["id"])["total_weight_lb"] == 0

    assignment = assign_order(load["id"], order["id"], expected_version=v0)
    mid = get_load(load["id"])
    assert mid["total_weight_lb"] == 400
    assert mid["version"] == v0 + 1
    assert get_work_order(order["id"])["processing_status"] == "SCHEDULED"

    unassign_order(load["id"], assignment["id"], expected_version=mid["version"])
    end = get_load(load["id"])
    assert end["total_weight_lb"] == 0, (
        f"unassign must restore the pre-assign weight exactly, got "
        f"{end['total_weight_lb']}"
    )
    assert end["version"] == mid["version"] + 1
    assert get_assignment(assignment["id"])["status"] == "REMOVED"
    assert get_work_order(order["id"])["processing_status"] == "RECEIVED"


def test_multi_order_weight_invariant_after_partial_unassign(api):
    """PRD §3.5: "Capacity is enforced by weight: a load's `total_weight_lb`
    is the sum of `received_weight_lb` over its `ACTIVE` assignments, and an
    assignment that would push that total strictly above the furnace's
    `max_load_weight_lb` is rejected with `ERR_LOAD_WEIGHT_EXCEEDED` — a load
    landing exactly at the maximum is permitted."
    PRD §3.5: "It moves the assignment from `ACTIVE` to `REMOVED`, returns the
    order to `RECEIVED` when its `retreat_count` is 0 or to
    `AWAITING_RETREAT` when the lot has already been re-treated at least once,
    recomputes the load's `total_weight_lb`, and bumps the load's `version`."

    Design: Difficulty/compensating_invariant/assign_unassign_restores_load_weight
    """
    shop = setup_shop(qualified=False)
    order_600 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=600
    )
    order_400 = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=400
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order_600["id"])
    asgmt_400 = assign_order(load["id"], order_400["id"])
    assert get_load(load["id"])["total_weight_lb"] == 1000

    unassign_order(load["id"], asgmt_400["id"])
    after = get_load(load["id"])
    assert after["total_weight_lb"] == 600, (
        "total must equal the sum over the remaining ACTIVE assignment, got "
        f"{after['total_weight_lb']}"
    )
    assert get_work_order(order_400["id"])["processing_status"] == "RECEIVED"
    assert get_work_order(order_600["id"])["processing_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers / occ_stale_version_conflict_and_fresh_retry
# ---------------------------------------------------------------------------

def test_occ_stale_version_conflict_and_fresh_retry(api):
    """PRD §2.9: "Exactly two write operations are concurrency-guarded, both
    targeting a LoadBatch: assigning a work order to a load, and removing an
    assignment from a load. Each requires the non-optional request field
    `expected_load_batch_version`, carrying the load's `version` as the client
    last observed it. If that value does not equal the LoadBatch's current
    `version` — because another write (an assign, an unassign, or a cascade
    such as an abort or an order cancellation) has advanced it since the
    client's read — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from rebuilding a load it has not
    observed."

    Design: Corner/cross_cutting_layers/occ_stale_version_conflict_and_fresh_retry
    """
    shop = setup_shop(qualified=False)
    order_1 = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    order_2 = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    stale_version = get_load(load["id"])["version"]

    # First assign succeeds and advances the load version.
    assign_order(load["id"], order_1["id"], expected_version=stale_version)
    fresh_version = get_load(load["id"])["version"]
    assert fresh_version == stale_version + 1

    # A second assign still carrying the pre-write version is rejected.
    res = api.create_load_assignment(
        load["id"],
        {
            "work_order_id": order_2["id"],
            "expected_load_batch_version": stale_version,
        },
        SCHED,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    assert get_work_order(order_2["id"])["processing_status"] == "RECEIVED"

    # Retrying with the freshly read version succeeds.
    retry = assign_order(load["id"], order_2["id"], expected_version=fresh_version)
    assert retry["status"] == "ACTIVE"
    after = get_load(load["id"])
    assert after["version"] == fresh_version + 1
    assert after["total_weight_lb"] == 200
    assert get_work_order(order_2["id"])["processing_status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel_scheduled_order_releases_assignment
# ---------------------------------------------------------------------------

def test_cancel_scheduled_order_releases_assignment(api):
    """PRD §3.8: "Cancellation, likewise a `CustomerServiceRep` action, is
    possible only while the order is `RECEIVED` or `SCHEDULED`
    (`ERR_WORK_ORDER_NOT_CANCELLABLE`, HTTP 409) and lands in the terminal
    `CANCELLED` status. Cancelling a `SCHEDULED` order additionally flips its
    `ACTIVE` assignment to `REMOVED`, recomputes the load's `total_weight_lb`,
    and increments the load's `version` by one."

    Design: Corner/state_machines/cancel_scheduled_order_releases_assignment
    """
    shop = setup_shop(qualified=False)
    order = create_work_order(
        shop["customer"]["id"], shop["recipe"]["id"], received_weight_lb=400
    )
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    v0 = get_load(load["id"])["version"]
    assignment = assign_order(load["id"], order["id"])
    assert get_load(load["id"])["version"] == v0 + 1

    cancelled = validate_success(api.cancel_work_order(order["id"], CSR), 200)
    assert cancelled["processing_status"] == "CANCELLED"

    after = get_load(load["id"])
    assert after["total_weight_lb"] == 0
    assert after["version"] == v0 + 2, (
        "assign bumped the version once and the cancel cascade bumps it "
        f"again; expected {v0 + 2}, got {after['version']}"
    )
    assert get_assignment(assignment["id"])["status"] == "REMOVED"


# ---------------------------------------------------------------------------
# Corner: state_machines / unassign_retreat_order_returns_awaiting_retreat
# ---------------------------------------------------------------------------

def test_unassign_retreat_order_returns_awaiting_retreat(api):
    """PRD §3.5: "It moves the assignment from `ACTIVE` to `REMOVED`, returns
    the order to `RECEIVED` when its `retreat_count` is 0 or to
    `AWAITING_RETREAT` when the lot has already been re-treated at least once,
    recomputes the load's `total_weight_lb`, and bumps the load's `version`."

    Design: Corner/state_machines/unassign_retreat_order_returns_awaiting_retreat
    """
    bundle = setup_failed_order(recipe_overrides={"max_retreats": 2})
    order = retreat_order_once(bundle)
    assert order["retreat_count"] == 1
    assert order["processing_status"] == "AWAITING_RETREAT"

    load2 = create_load(
        bundle["shop"]["furnace"]["id"], bundle["shop"]["recipe"]["id"],
        scheduled_start_at="2026-08-03T08:00:00Z",
        scheduled_end_at="2026-08-03T12:00:00Z",
    )
    assignment2 = assign_order(load2["id"], order["id"])
    assert get_work_order(order["id"])["processing_status"] == "SCHEDULED"

    unassign_order(load2["id"], assignment2["id"])
    reverted = get_work_order(order["id"])
    assert reverted["processing_status"] == "AWAITING_RETREAT", (
        "retreat_count > 0, so unassign must return the order to "
        f"AWAITING_RETREAT, got {reverted['processing_status']}"
    )
    assert get_assignment(assignment2["id"])["status"] == "REMOVED"
    assert get_load(load2["id"])["total_weight_lb"] == 0
