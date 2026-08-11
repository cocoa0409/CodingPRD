"""Dispatch, the 12-hour account spacing buffer, and the shipment carriage axis."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    assert_shipment,
    read_cycle,
    set_clock,
    setup_allocated_cycle,
    setup_dispatched_cycle,
    setup_household,
    setup_shipment_in_transit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_second_child_and_subscription,
    allocate_cycle,
    charge_cycle,
    dispatch_cycle,
    generate_cycle,
    lock_cycle,
    shipment_for_cycle,
)

OPS = TEST_USERS["ops_admin_headers"]


def _two_charged_cycles_on_one_household(api, email_prefix):
    """One household, two children, two ACTIVE subscriptions, both cycles charged."""
    ctx = setup_household(api, email_prefix=email_prefix)
    _child_b, subscription_b = add_second_child_and_subscription(api, ctx)

    cycle_a = generate_cycle(api, ctx["subscription"]["id"])
    cycle_b = generate_cycle(api, subscription_b["id"])
    allocate_cycle(api, cycle_a["id"])
    allocate_cycle(api, cycle_b["id"])

    set_clock(api, "2026-06-08T00:00:00Z")
    lock_cycle(api, cycle_a["id"])
    charge_cycle(api, cycle_a["id"])
    lock_cycle(api, cycle_b["id"])
    charge_cycle(api, cycle_b["id"])
    return ctx, cycle_a, cycle_b


# ==========================================================================
# The point-plus-buffer spacing rule
# ==========================================================================
def test_two_dispatches_exactly_twelve_hours_apart_are_allowed(api):
    """PRD §3.8: "One further rule protects the household's doorstep: no other shipment for
    the same account that is not already `RETURNED` may have a `dispatched_at` within 12
    hours of the logical clock. The comparison is strict in both directions — a gap of
    exactly 12 hours is allowed, while 11 hours and 59 minutes is refused with
    `ERR_SHIPMENT_SPACING_VIOLATION` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/shipment_spacing_gap_of_exactly_twelve_hours_is_allowed
    """
    ctx, cycle_a, cycle_b = _two_charged_cycles_on_one_household(api, "space")
    dispatch_cycle(api, cycle_a["id"])
    set_clock(api, "2026-06-08T12:00:00Z")

    dispatched = validate_success(
        api.dispatch_cycle(cycle_b["id"], OPS, {"service_level": "STANDARD"})
    )
    assert dispatched["status"] == "DISPATCHED"
    assert_same_instant(
        dispatched["dispatched_at"], "2026-06-08T12:00:00Z", "Cycle.dispatched_at"
    )


def test_a_second_dispatch_creates_a_second_shipment_for_the_household(api):
    """PRD §3.8: "Dispatch creates a `Shipment` in status `CREATED`, with its `cycle_id` set
    to the dispatching cycle, its `gift_order_id` null, its `account_id` set to the
    subscription's household, and its `dispatched_at` set to the logical clock."
    PRD §3.8: "The comparison is strict in both directions — a gap of exactly 12 hours is
    allowed, while 11 hours and 59 minutes is refused with `ERR_SHIPMENT_SPACING_VIOLATION`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/shipment_spacing_gap_of_exactly_twelve_hours_is_allowed
    """
    ctx, cycle_a, cycle_b = _two_charged_cycles_on_one_household(api, "space1b")
    dispatch_cycle(api, cycle_a["id"])
    set_clock(api, "2026-06-08T12:00:00Z")
    dispatch_cycle(api, cycle_b["id"])

    _shipments, meta = validate_paginated(
        api.list_shipments(OPS, {"account_id": ctx["account_id"], "limit": 100})
    )
    assert meta["total_count"] == 2


def test_a_dispatch_eleven_hours_after_the_last_one_is_refused(api):
    """PRD §3.8: "The rule is symmetric around the moment of dispatch and counts across both
    pipelines: a gift shipment blocks a cycle shipment and a cycle shipment blocks a gift
    shipment. This is a point-plus-buffer geometry and should not be confused with the
    interval geometries used for pauses and cycle windows."
    PRD §3.8: "The comparison is strict in both directions — a gap of exactly 12 hours is
    allowed, while 11 hours and 59 minutes is refused with `ERR_SHIPMENT_SPACING_VIOLATION`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/shipment_point_buffer_under_twelve_hours_rejected
    """
    ctx, cycle_a, cycle_b = _two_charged_cycles_on_one_household(api, "space2")
    dispatch_cycle(api, cycle_a["id"])
    set_clock(api, "2026-06-08T11:00:00Z")

    resp = api.dispatch_cycle(cycle_b["id"], OPS, {"service_level": "STANDARD"})
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_SPACING_VIOLATION.value, 409)

    assert read_cycle(api, cycle_b["id"])["status"] == "CUTOFF_LOCKED"


def test_the_refused_dispatch_creates_no_second_shipment(api):
    """PRD §3.8: "Dispatch creates a `Shipment` in status `CREATED`, with its `cycle_id` set
    to the dispatching cycle, its `gift_order_id` null, its `account_id` set to the
    subscription's household, and its `dispatched_at` set to the logical clock."
    PRD §2.6: "One rung, and only one, breaks the rule that a rejected request leaves the
    database untouched; it is called out explicitly in section 3.6 where it lives."

    Design: Difficulty/resource_temporal_overlap/shipment_point_buffer_under_twelve_hours_rejected
    """
    ctx, cycle_a, cycle_b = _two_charged_cycles_on_one_household(api, "space2b")
    dispatch_cycle(api, cycle_a["id"])
    set_clock(api, "2026-06-08T11:00:00Z")
    validate_error(
        api.dispatch_cycle(cycle_b["id"], OPS, {"service_level": "STANDARD"}),
        ApiErrorId.ERR_SHIPMENT_SPACING_VIOLATION.value,
        409,
    )

    _shipments, meta = validate_paginated(
        api.list_shipments(OPS, {"account_id": ctx["account_id"], "limit": 100})
    )
    assert meta["total_count"] == 1


# ==========================================================================
# The cycle's own dispatch precondition
# ==========================================================================
def test_dispatching_a_cycle_that_has_not_locked_is_refused(api):
    """PRD §3.8: "A cycle leaves the warehouse only from `CUTOFF_LOCKED`, and only when its
    `payment_status` is `FULLY_COVERED` or `CHARGED`"
    PRD §3.5: "Any attempt whose from-state is not in the target transition's declared set
    is refused with `ERR_CYCLE_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_dispatch_before_lock_rejected
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="disp")
    resp = api.dispatch_cycle(cycle["id"], OPS, {"service_level": "STANDARD"})
    validate_error(resp, ApiErrorId.ERR_CYCLE_STATE_INVALID.value, 409)

    after = read_cycle(api, cycle["id"])
    assert after["status"] == "ALLOCATED"
    assert after.get("dispatched_at") is None
    _shipments, meta = validate_paginated(api.list_shipments(OPS, {"cycle_id": cycle["id"]}))
    assert meta["total_count"] == 0


# ==========================================================================
# Carriage
# ==========================================================================
def test_delivering_a_shipment_still_in_created_is_refused(api):
    """PRD §3.8: "A shipment walks `CREATED → PICKED → IN_TRANSIT → DELIVERED`, with
    `RETURNED` as its terminal state, and every step is `OpsAdmin` work. Any step whose
    from-state does not match is refused with `ERR_SHIPMENT_STATE_INVALID` (HTTP 409)."
    PRD §3.8: "An optional `service_level` may be supplied, defaulting to `STANDARD`, with
    `EXPEDITED` as the only alternative."

    Design: Corner/state_machines/corner_shipment_deliver_from_created_rejected
    """
    ctx, cycle, shipment = setup_dispatched_cycle(
        api, email_prefix="shipstate", service_level="EXPEDITED"
    )
    resp = api.deliver_shipment(shipment["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_STATE_INVALID.value, 409)

    after = validate_success(api.get_shipment(shipment["id"], OPS))
    assert_shipment(after)
    assert after["status"] == "CREATED"
    assert after.get("delivered_at") is None
    assert after["service_level"] == "EXPEDITED"


def test_handing_an_expedited_shipment_to_the_carrier_sets_a_one_day_eta(api):
    """PRD §3.8: "Handing the shipment to the carrier sets its `eta_days`: 1 day when
    `service_level` is `EXPEDITED`, and 3 days otherwise."
    PRD §3.8: "Dispatch creates a `Shipment` in status `CREATED`, with its `cycle_id` set to
    the dispatching cycle, its `gift_order_id` null, its `account_id` set to the
    subscription's household, and its `dispatched_at` set to the logical clock."

    Design: Corner/calculations/corner_shipment_eta_days_expedited_is_one
    """
    ctx, cycle, shipment = setup_dispatched_cycle(
        api, email_prefix="eta", service_level="EXPEDITED"
    )
    validate_success(api.pick_shipment(shipment["id"], OPS))
    in_transit = validate_success(api.transit_shipment(shipment["id"], OPS))

    assert in_transit["status"] == "IN_TRANSIT"
    assert in_transit["eta_days"] == 1
    assert in_transit.get("gift_order_id") is None
    assert in_transit["account_id"] == ctx["account_id"]


def test_the_carrier_exception_loop_is_traversable_exactly_twice(api):
    """PRD §3.8: "Carriage may go wrong twice: a shipment `IN_TRANSIT` may be moved to
    `EXCEPTION`, incrementing its `exception_count`, and may then be retried back
    `EXCEPTION → IN_TRANSIT`."

    Design: Difficulty/non_linear_state_machine/shipment_exception_retry_loop_capped_at_two
    """
    ctx, cycle, shipment = setup_shipment_in_transit(api, email_prefix="ship")

    first = validate_success(api.exception_shipment(shipment["id"], OPS))
    assert first["status"] == "EXCEPTION"
    assert first["exception_count"] == 1
    assert validate_success(api.retry_shipment(shipment["id"], OPS))["status"] == "IN_TRANSIT"

    second = validate_success(api.exception_shipment(shipment["id"], OPS))
    assert second["status"] == "EXCEPTION"
    assert second["exception_count"] == 2
    assert validate_success(api.retry_shipment(shipment["id"], OPS))["status"] == "IN_TRANSIT"


def test_a_third_exception_hits_the_retry_cap_rather_than_the_state_error(api):
    """PRD §3.8: "The retry loop is capped at 2 exceptions — a third exception on a shipment
    whose `exception_count` has already reached 2 is refused with
    `ERR_SHIPMENT_RETRY_CAP_EXCEEDED` (HTTP 409) rather than the generic state error, because
    the from-state `IN_TRANSIT` is itself perfectly valid."

    Design: Difficulty/non_linear_state_machine/shipment_exception_retry_loop_capped_at_two
    """
    ctx, cycle, shipment = setup_shipment_in_transit(api, email_prefix="ship2")
    for _ in range(2):
        validate_success(api.exception_shipment(shipment["id"], OPS))
        validate_success(api.retry_shipment(shipment["id"], OPS))

    resp = api.exception_shipment(shipment["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_RETRY_CAP_EXCEEDED.value, 409)

    after = validate_success(api.get_shipment(shipment["id"], OPS))
    assert after["exception_count"] == 2
    assert after["status"] == "IN_TRANSIT"


def test_a_delivered_shipment_may_still_be_marked_returned(api):
    """PRD §3.8: "A shipment may be marked returned from `EXCEPTION` or from `DELIVERED`,
    settling in `RETURNED`."
    PRD §3.8: "Confirming carrier delivery moves the shipment `IN_TRANSIT → DELIVERED` and
    stamps its `delivered_at`"
    PRD §3.8: "Handing the shipment to the carrier sets its `eta_days`: 1 day when
    `service_level` is `EXPEDITED`, and 3 days otherwise."

    Design: Corner/endpoints/corner_shipment_return_after_delivery
    """
    ctx, cycle, shipment = setup_shipment_in_transit(api, email_prefix="shipret")
    validate_success(api.deliver_shipment(shipment["id"], OPS))

    returned = validate_success(api.return_shipment(shipment["id"], OPS))
    assert returned["status"] == "RETURNED"

    read_back = validate_success(api.get_shipment(shipment["id"], ctx["headers"]))
    assert read_back["status"] == "RETURNED"
    assert_same_instant(
        read_back["delivered_at"], "2026-06-08T00:00:00Z", "Shipment.delivered_at"
    )
    assert read_back["eta_days"] == 3
