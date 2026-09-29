"""Thresholds that are inclusive, and candidate sets that come back empty.

A bucket holding exactly its capacity is full, and a dispatch with nothing
eligible is an error rather than a quiet no-op.
"""
from test_helpers import (
    ApiErrorId,
    assert_delivery_assignment,
    assert_instant,
    assert_store_counters,
    burger_item_payload,
    create_aggregator_channel_payload,
    create_courier_network,
    create_order_payload,
    dispatch_order,
    env_partner_headers,
    env_store_headers,
    order_line,
    place_injected_order,
    place_order,
    read_network,
    read_order,
    read_store,
    set_clock,
    setup_published_store,
    validate_error,
    validate_paginated,
    validate_success,
)

BURGER_ONLY = {"item_payloads": [burger_item_payload()]}
BURGER_LINE = [order_line("BURGER", 1)]
AGGREGATOR_BURGER = dict(
    channel_payloads=[create_aggregator_channel_payload()], item_payloads=[burger_item_payload()]
)


def _pickup_order_payload(env, external_ref):
    return create_order_payload(
        env["store"]["id"], env["channel"]["id"], external_ref=external_ref,
        fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0,
    )


def _fill_the_bucket(env):
    first = place_order(
        env, external_ref="MP-1001", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    second = place_order(
        env, external_ref="MP-1002", fulfillment_mode="PICKUP", lines=BURGER_LINE, tip_cents=0
    )
    return first, second


def test_a_bucket_holding_exactly_its_capacity_admits_no_more(api):
    """Two orders in a bucket of capacity two make the third one fail.

    PRD: "Admission fails when `bucket_load` is greater than or equal to
    `prep_capacity_per_bucket` — the comparison is inclusive, so a bucket already
    holding exactly its capacity is full — and the request is refused with
    `ERR_CAPACITY_BUCKET_FULL`."

    Design: Difficulty/boundary_precision_check/capacity_bucket_full_at_inclusive_threshold
    """
    env = setup_published_store(**BURGER_ONLY)
    assert env["store"]["prep_capacity_per_bucket"] == 2
    first, second = _fill_the_bucket(env)
    assert first["bucket_index"] == 44
    assert second["bucket_index"] == 44

    response = api.create_order(
        _pickup_order_payload(env, "MP-1003"), env_partner_headers(env)
    )

    validate_error(response, ApiErrorId.ERR_CAPACITY_BUCKET_FULL, 409)
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=2, reserved_prep_slots=2)


def test_the_next_bucket_admits_the_order_the_full_one_refused(api):
    """Fifteen minutes later the identical request lands in bucket 45 and is taken.

    PRD: "The `bucket_index` is that local minute of day divided by 15 and rounded
    down to a whole number, giving 96 buckets per local day." "The preparation
    figure `prep_minutes` starts at the store's `base_prep_minutes`, adds 2 minutes
    for each order counted in the load figure `load_count`, and adds a further 8
    minutes when the store's posture is `THROTTLED`."

    Design: Difficulty/boundary_precision_check/capacity_bucket_full_at_inclusive_threshold
    """
    env = setup_published_store(**BURGER_ONLY)
    _fill_the_bucket(env)

    set_clock("2026-08-03T16:15:00Z")
    third = validate_success(
        api.create_order(_pickup_order_payload(env, "MP-1003"), env_partner_headers(env)),
        expected_status=201,
    )

    assert third["bucket_index"] == 45, (
        f"local minute 675 divided by 15, got {third['bucket_index']}"
    )
    assert_instant(third["promised_ready_at"], "2026-08-03T16:31:00Z", "promised_ready_at")
    assert_store_counters(read_store(env["store"]["id"]), open_order_count=3, reserved_prep_slots=3)


def test_dispatch_with_no_eligible_network_is_an_error_not_a_null_assignment(api):
    """A marketplace network cannot carry an aggregator order and an inactive one never plays.

    PRD: "A network is eligible for a given order when all three of the following
    hold: its `is_active` is true; either its `network_type` is `COURIER` or the
    order's channel has a `channel_type` of `MARKETPLACE`; and its occupancy count
    at the current logical clock is strictly less than its
    `max_concurrent_assignments`. If no network is eligible, dispatch is refused
    with `ERR_NO_ELIGIBLE_COURIER_NETWORK` — an empty candidate set is always an
    error and never a null assignment."

    Design: Difficulty/boundary_precision_check/empty_courier_candidate_set_rejected
    """
    env = setup_published_store(**AGGREGATOR_BURGER)
    marketplace_network = create_courier_network(
        code="N_MKT", network_type="MARKETPLACE", priority_rank=1, per_delivery_fee_cents=300,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=5,
    )
    create_courier_network(
        code="N_FAST", network_type="COURIER", priority_rank=2, per_delivery_fee_cents=650,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=1,
        is_active=False,
    )
    order = place_injected_order(
        env, external_ref="AG-2001", fulfillment_mode="DELIVERY", lines=BURGER_LINE, tip_cents=0
    )

    response = api.dispatch_order(order["id"], env_store_headers(env))

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_COURIER_NETWORK, 409)
    _rows, meta = validate_paginated(
        api.list_delivery_assignments(env_store_headers(env), params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, "the refused dispatch created nothing"
    assert read_network(marketplace_network["id"])["open_assignment_count"] == 0
    assert read_order(order["id"])["fulfillment_status"] == "PREPARING"


def test_registering_one_eligible_courier_network_makes_the_same_dispatch_win(api):
    """The offer goes to the only eligible network and occupies it for sla plus buffer.

    PRD: "A new assignment records the `order_id` it serves and the
    `courier_network_id` that won selection, starts in `OFFERED` with `offered_at`
    stamped from the clock, and sets `occupancy_until` to `offered_at` advanced by
    the network's `handoff_sla_seconds` and then by its `dispatch_buffer_seconds`."

    Design: Difficulty/boundary_precision_check/empty_courier_candidate_set_rejected
    """
    env = setup_published_store(**AGGREGATOR_BURGER)
    marketplace_network = create_courier_network(
        code="N_MKT", network_type="MARKETPLACE", priority_rank=1, per_delivery_fee_cents=300,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=5,
    )
    create_courier_network(
        code="N_FAST", network_type="COURIER", priority_rank=2, per_delivery_fee_cents=650,
        handoff_sla_seconds=600, dispatch_buffer_seconds=120, max_concurrent_assignments=1,
        is_active=False,
    )
    order = place_injected_order(
        env, external_ref="AG-2001", fulfillment_mode="DELIVERY", lines=BURGER_LINE, tip_cents=0
    )
    validate_error(
        api.dispatch_order(order["id"], env_store_headers(env)),
        ApiErrorId.ERR_NO_ELIGIBLE_COURIER_NETWORK, 409,
    )

    economy_network = create_courier_network(
        code="N_ECON", network_type="COURIER", priority_rank=3, per_delivery_fee_cents=450,
        handoff_sla_seconds=900, dispatch_buffer_seconds=180, max_concurrent_assignments=2,
    )
    assignment = dispatch_order(env, order["id"])

    assert_delivery_assignment(assignment)
    assert assignment["courier_network_id"] == economy_network["id"], (
        "the only eligible network wins even though it has the worst priority rank"
    )
    assert assignment["state"] == "OFFERED"
    assert_instant(assignment["offered_at"], "2026-08-03T16:00:00Z", "offered_at")
    assert_instant(assignment["occupancy_until"], "2026-08-03T16:18:00Z", "occupancy_until")
    assert read_network(economy_network["id"])["open_assignment_count"] == 1
    assert read_network(marketplace_network["id"])["open_assignment_count"] == 0
