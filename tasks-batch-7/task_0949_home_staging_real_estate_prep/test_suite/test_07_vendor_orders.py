"""Partner rental orders: placement arithmetic, the cancellation cutoff and vendor terms."""

from test_helpers import (
    COORD,
    WAREHOUSE,
    ApiErrorId,
    assert_money,
    assert_rental_order,
    assert_same_instant,
    assert_vendor,
    set_clock,
    setup_vacant_project_staged,
    setup_vacant_pull_committed,
    setup_vacant_pull_submitted,
    setup_vendor_only,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_placing_a_delivered_order_again_is_an_invalid_order_state(api):
    """PRD §2.7: "Rung 23: the rental order's `state` is a legal origin for the requested
    transition — and in particular a `DELIVERED` or `RETURNED` order can no longer be
    cancelled at any price; otherwise `ERR_ORDER_INVALID_STATE`, HTTP 409."
    PRD §3.4: "`earliest_delivery_date` is `placed_at` plus the vendor's `lead_time_days`
    days, and it is the floor for any install instant that consumes this order."
    PRD §3.4: "`cancel_cutoff_date` is `earliest_delivery_date` minus the vendor's
    `cancel_cutoff_days` days."
    PRD §3.4: "`effective_term_cycles` is the larger of the project's lease `initial_cycles`
    and the vendor's `min_lease_cycles`, falling back to 3 cycles as the project figure when
    no lease row exists yet."
    PRD §3.4: "`monthly_rate_total` is the order's `unit_count` multiplied by a vendor unit
    base rate of 85.00 multiplied by the vendor's `rate_multiplier`, rounded half-up to two
    decimal places **once per order and not per unit**."

    Design: Corner/state_machines/rental_order_place_twice_rejected_as_order_invalid_state
    """
    ctx = setup_vacant_project_staged()

    resp = api.place_rental_order(ctx["ro_id"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
    order = validate_success(api.get_rental_order(ctx["ro_id"], WAREHOUSE))
    assert_rental_order(order)
    assert order["state"] == "DELIVERED"
    assert_same_instant(order["earliest_delivery_date"], "2026-06-08T00:00:00Z",
                        "order.earliest_delivery_date")
    assert_same_instant(order["cancel_cutoff_date"], "2026-06-04T00:00:00Z",
                        "order.cancel_cutoff_date")
    assert order["effective_term_cycles"] == 6
    assert_money(order["monthly_rate_total"], 1147.50, "order.monthly_rate_total")


def test_cancelling_on_the_cutoff_day_takes_the_late_arm_and_the_full_fee(api):
    """PRD §3.4: "Cancellation is where the money turns: from `DRAFT` or `PLACED`, with the
    logical clock strictly before `cancel_cutoff_date`, the order moves to `CANCELLED` and
    its `cancellation_fee` is 25 percent of `monthly_rate_total`; from `PLACED` or
    `CONFIRMED`, with the clock on or after `cancel_cutoff_date`, it moves to
    `CANCELLED_LATE` and the fee is 100 percent of `monthly_rate_total`."
    PRD §3.4: "In both arms the fee is rounded half-up to two decimal places and every
    vendor pull line pointing at that order is dropped."

    Design: Corner/state_machines/rental_order_cancelled_late_after_cutoff_charges_full_rate
    """
    ctx = setup_vacant_pull_committed()
    set_clock("2026-06-06T00:00:00Z")

    resp = api.cancel_rental_order(ctx["ro_id"], WAREHOUSE)

    validate_success(resp)
    order = validate_success(api.get_rental_order(ctx["ro_id"], WAREHOUSE))
    assert order["state"] == "CANCELLED_LATE"
    assert_money(order["monthly_rate_total"], 459.00, "order.monthly_rate_total")
    assert_same_instant(order["cancel_cutoff_date"], "2026-06-04T00:00:00Z",
                        "order.cancel_cutoff_date")
    assert_money(order["cancellation_fee"], 459.00, "order.cancellation_fee")
    line = validate_success(api.get_pull_line(ctx["line_v"], WAREHOUSE))
    assert line["state"] == "DROPPED"


def test_a_vendor_can_be_suspended_through_the_terms_update(api):
    """PRD §3.4: "A vendor's `status` starts at `ACTIVE` and may be moved to `SUSPENDED`;
    only an `ACTIVE` vendor may have an order placed against it."
    PRD §2.4: "`version` is an integer that begins at 1 when the row is created and
    increments by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/vendor_suspended_status_is_reachable_via_patch
    """
    ctx = setup_vendor_only()

    resp = api.update_vendor(ctx["vendor_id"], {"status": "SUSPENDED"}, WAREHOUSE)

    data = validate_success(resp)
    assert_vendor(data)
    assert data["status"] == "SUSPENDED"
    assert data["version"] == 2


def test_an_install_before_the_vendor_lead_time_is_refused(api):
    """PRD §2.7: "Rung 42: the install's `scheduled_at` is on or after every consumed rental
    order's `earliest_delivery_date`; otherwise `ERR_VENDOR_LEAD_TIME_VIOLATION`, HTTP 422."
    PRD §3.4: "Three capacity and authority checks guard it: the install instant must be on
    or after every consumed rental order's `earliest_delivery_date`; the requested
    `initial_cycles` must be at least 3; and every consumed order's `effective_term_cycles`
    must be no greater than `initial_cycles` plus 6."
    PRD §3.4: "**Scheduling the install is what creates the lease**, in state `PENDING`,
    with the supplied `initial_cycles`."

    Design: Corner/validations/install_before_vendor_lead_time_rejected
    """
    ctx = setup_vacant_pull_submitted()
    validate_success(api.commit_pull(ctx["pull_id"], ctx["proj_v"], WAREHOUSE))

    resp = api.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-05T09:00:00Z", "crew_size": 3, "initial_cycles": 6}, COORD)

    validate_error(resp, ApiErrorId.ERR_VENDOR_LEAD_TIME_VIOLATION.value, 422)
    order = validate_success(api.get_rental_order(ctx["ro_id"], WAREHOUSE))
    assert_same_instant(order["earliest_delivery_date"], "2026-06-08T00:00:00Z",
                        "order.earliest_delivery_date")
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "PULL_OPEN"
    _, meta = validate_paginated(api.list_leases(COORD, params={"project_id": ctx["proj_id"]}))
    assert meta["total_count"] == 0, "a refused install schedules no lease"


def test_a_vendor_minimum_term_the_project_can_never_reach_is_refused(api):
    """PRD §2.7: "Rung 44: every consumed rental order's `effective_term_cycles` is less
    than or equal to the lease's `initial_cycles` plus 6."
    PRD §2.7: "A vendor's own minimum term **may** exceed the project's term — that
    shortfall is billed rather than blocked — but a vendor minimum the project could never
    reach even by extending to the six-cycle ceiling is rejected outright with
    `ERR_VENDOR_MIN_TERM_VIOLATION`, HTTP 422."

    Design: Corner/validations/vendor_minimum_term_unreachable_even_at_the_extension_cap_rejected
    """
    ctx = setup_vacant_pull_submitted()
    validate_success(api.commit_pull(ctx["pull_id"], ctx["proj_v"], WAREHOUSE))

    resp = api.schedule_install(
        ctx["proj_id"],
        {"scheduled_at": "2026-06-10T09:00:00Z", "crew_size": 3, "initial_cycles": 3}, COORD)

    validate_error(resp, ApiErrorId.ERR_VENDOR_MIN_TERM_VIOLATION.value, 422)
    order = validate_success(api.get_rental_order(ctx["ro_id"], WAREHOUSE))
    assert order["effective_term_cycles"] == 12
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "PULL_OPEN"
