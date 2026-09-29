"""Dock windows, carrier day capacity, the deadline gate and pickup completion."""

from test_helpers import (
    ADMIN,
    api_client,
    assert_instant,
    assert_pickup_appointment,
    book_appointment,
    bootstrap_marketplace,
    completion_payload,
    create_warehouse,
    get_success_data,
    pickup_appointment_payload,
    pay_order,
    read_appointment,
    read_order,
    set_clock,
    setup_paid_auction_order,
    setup_paid_fixed_price_order,
    setup_fixed_price_order,
    setup_two_paid_fixed_price_orders,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-DOCK-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

ONE_DOOR_WAREHOUSE = {"dock_door_count": 1}


def _book(env, order, start, end, *, bol_number, warehouse_id=None, carrier_id=None):
    """The raw booking call, so the caller can inspect the status and the error."""
    return api_client.book_pickup_appointment(
        order["id"],
        pickup_appointment_payload(
            warehouse_id or env["warehouse"]["id"],
            carrier_id or env["carrier"]["id"],
            start,
            end,
            bol_number,
        ),
        env["buyer_headers"],
    )


def test_a_window_starting_when_the_previous_one_ends_still_collides():
    """The buffer pads the booked interval on both sides, so a back-to-back request on
    the only door is refused.

    PRD 3.7: "The occupation interval a booking claims is the requested window itself,
    treated as inclusive at `window_start_at` and exclusive at `window_end_at`, and it
    is padded by the buffer on both sides for the purpose of detecting collisions."
    PRD 3.7: "Formally, an existing appointment conflicts with the request when both of
    the following hold: the requested `window_start_at` falls strictly before the
    existing appointment's `window_end_at` advanced by the buffer, and the existing
    appointment's `window_start_at` falls strictly before the requested `window_end_at`
    advanced by the buffer."
    PRD 3.7: "To make the buffer arithmetic concrete: with a single door and a 15-minute
    buffer, an appointment already occupying 14:00 to 15:00 blocks a request starting at
    15:00, because 15:00 falls strictly before 15:15, while a request starting at 15:15
    is accepted because 15:15 does not fall strictly before 15:15."
    PRD 3.7: "When no door is eligible the booking is rejected with
    `ERR_DOCK_CAPACITY_EXHAUSTED` and no appointment is created."

    Design: Difficulty/resource_temporal_overlap/dock_door_conflict_uses_buffer_padded_half_open_windows
    """
    built = setup_two_paid_fixed_price_orders(warehouse_overrides=ONE_DOOR_WAREHOUSE)
    env = built["env"]
    held = book_appointment(
        env,
        built["order_a"],
        window_start_at="2026-08-10T14:00:00Z",
        window_end_at="2026-08-10T15:00:00Z",
        bol_number="BOL-A1",
    )
    assert held["dock_door_number"] == 1

    adjacent = _book(
        env,
        built["order_b"],
        "2026-08-10T15:00:00Z",
        "2026-08-10T16:00:00Z",
        bol_number="BOL-B1",
    )
    validate_error(adjacent, "ERR_DOCK_CAPACITY_EXHAUSTED", 422)

    assert read_order(env, built["order_b"]["id"])["logistics_status"] == "AWAITING_APPOINTMENT"
    assert total_count(
        api_client.list_pickup_appointments(
            ADMIN, {"sale_order_id": built["order_b"]["id"]}
        )
    ) == 0
    assert read_appointment(env, held["id"])["appointment_status"] == "SCHEDULED"


def test_the_same_door_is_reusable_at_exactly_one_buffer_of_distance():
    """At exactly the buffer the strict comparison is false, so the door is free again
    and the second appointment lands on it.

    PRD 3.7: "…while a request starting at 15:15 is accepted because 15:15 does not fall
    strictly before 15:15."
    PRD 3.7: "The eligible doors are those numbers, from 1 through `dock_door_count`, on
    which no such conflict exists, and the platform assigns the **lowest-numbered**
    eligible door; no further tie-break is needed because door numbers are unique within
    a warehouse."
    PRD 3.7: "An accepted booking advances the order `AWAITING_APPOINTMENT →
    APPOINTMENT_SCHEDULED` and advances the order's `version` by one."

    Design: Difficulty/resource_temporal_overlap/dock_door_conflict_uses_buffer_padded_half_open_windows
    """
    built = setup_two_paid_fixed_price_orders(warehouse_overrides=ONE_DOOR_WAREHOUSE)
    env = built["env"]
    held = book_appointment(
        env,
        built["order_a"],
        window_start_at="2026-08-10T14:00:00Z",
        window_end_at="2026-08-10T15:00:00Z",
        bol_number="BOL-A1",
    )

    refused = _book(
        env,
        built["order_b"],
        "2026-08-10T15:00:00Z",
        "2026-08-10T16:00:00Z",
        bol_number="BOL-B1",
    )
    validate_error(refused, "ERR_DOCK_CAPACITY_EXHAUSTED", 422)

    accepted = validate_success(
        _book(
            env,
            built["order_b"],
            "2026-08-10T15:15:00Z",
            "2026-08-10T16:15:00Z",
            bol_number="BOL-B2",
        ),
        201,
    )
    assert_pickup_appointment(accepted)
    assert accepted["dock_door_number"] == 1
    assert_instant(accepted["window_start_at"], "2026-08-10T15:15:00Z")
    assert_instant(accepted["window_end_at"], "2026-08-10T16:15:00Z")

    assert total_count(
        api_client.list_pickup_appointments(
            ADMIN,
            {"warehouse_id": env["warehouse"]["id"], "appointment_status": "SCHEDULED"},
        )
    ) == 2
    assert read_order(env, built["order_a"]["id"])["logistics_status"] == "APPOINTMENT_SCHEDULED"
    assert read_order(env, built["order_b"]["id"])["logistics_status"] == "APPOINTMENT_SCHEDULED"
    assert read_appointment(env, held["id"])["dock_door_number"] == 1


def test_the_carrier_day_allowance_is_spent_by_a_disjoint_window_on_the_same_date():
    """The carrier limit counts appointments per UTC date rather than by overlap, so a
    window five hours clear of the first booking is still refused.

    PRD 3.7: "**The carrier's daily cap** is an aggregate limit checked only after a
    door has been found. Count the appointments naming the requested carrier whose
    `appointment_status` is `SCHEDULED` and whose `window_start_at` falls on the same
    UTC calendar date as the request; if that count plus one would exceed the carrier's
    `daily_pickup_capacity`, the booking is rejected with
    `ERR_CARRIER_DAY_CAPACITY_FULL`."
    PRD 3.7: "At band 13 the door selector runs, and at band 14 the carrier's daily cap
    is checked."

    Design: Difficulty/resource_temporal_overlap/carrier_daily_capacity_counts_per_utc_date_not_per_interval
    """
    built = setup_two_paid_fixed_price_orders(
        carrier_overrides={"daily_pickup_capacity": 1}
    )
    env = built["env"]
    first = book_appointment(
        env,
        built["order_a"],
        window_start_at="2026-08-10T14:00:00Z",
        window_end_at="2026-08-10T15:00:00Z",
        bol_number="BOL-C1",
    )
    assert first["dock_door_number"] == 1

    same_date = _book(
        env,
        built["order_b"],
        "2026-08-10T20:00:00Z",
        "2026-08-10T21:00:00Z",
        bol_number="BOL-D1",
    )
    error = validate_error(same_date, "ERR_CARRIER_DAY_CAPACITY_FULL", 422)
    assert error["error_id"] != "ERR_DOCK_CAPACITY_EXHAUSTED"

    assert read_order(env, built["order_b"]["id"])["logistics_status"] == "AWAITING_APPOINTMENT"
    assert total_count(
        api_client.list_pickup_appointments(
            ADMIN, {"carrier_id": env["carrier"]["id"], "appointment_status": "SCHEDULED"}
        )
    ) == 1


def test_the_carrier_allowance_resets_on_the_next_utc_date():
    """The identical clock time one calendar day later is admitted, and the carrier then
    holds one appointment per date.

    PRD 3.7: "The counter spans every warehouse — a carrier with a capacity of one
    appointment per day may take one booking on a given UTC date anywhere in the network
    and no more, but is free again on the next UTC date."
    PRD 3.7: "The eligible doors are those numbers, from 1 through `dock_door_count`, on
    which no such conflict exists, and the platform assigns the **lowest-numbered**
    eligible door; no further tie-break is needed because door numbers are unique within
    a warehouse."

    Design: Difficulty/resource_temporal_overlap/carrier_daily_capacity_counts_per_utc_date_not_per_interval
    """
    built = setup_two_paid_fixed_price_orders(
        carrier_overrides={"daily_pickup_capacity": 1}
    )
    env = built["env"]
    first = book_appointment(
        env,
        built["order_a"],
        window_start_at="2026-08-10T14:00:00Z",
        window_end_at="2026-08-10T15:00:00Z",
        bol_number="BOL-C1",
    )

    refused = _book(
        env,
        built["order_b"],
        "2026-08-10T20:00:00Z",
        "2026-08-10T21:00:00Z",
        bol_number="BOL-D1",
    )
    validate_error(refused, "ERR_CARRIER_DAY_CAPACITY_FULL", 422)

    next_date = validate_success(
        _book(
            env,
            built["order_b"],
            "2026-08-11T20:00:00Z",
            "2026-08-11T21:00:00Z",
            bol_number="BOL-D2",
        ),
        201,
    )
    assert next_date["dock_door_number"] == 1
    assert next_date["carrier_id"] == env["carrier"]["id"]
    assert_instant(next_date["window_start_at"], "2026-08-11T20:00:00Z")

    assert total_count(
        api_client.list_pickup_appointments(
            ADMIN, {"carrier_id": env["carrier"]["id"], "appointment_status": "SCHEDULED"}
        )
    ) == 2
    assert read_order(env, built["order_b"]["id"])["logistics_status"] == "APPOINTMENT_SCHEDULED"
    assert read_appointment(env, first["id"])["appointment_status"] == "SCHEDULED"


def test_a_partially_paid_order_cannot_book_an_otherwise_perfect_window():
    """Both doors are free and the window is well inside the deadline, yet the parent
    order's money dimension refuses the booking.

    PRD 3.7: "At band 9, the order's `logistics_status` must be `AWAITING_APPOINTMENT`,
    or the request is `ERR_ORDER_LOGISTICS_STATE_INVALID`. At band 10, the order's
    `payment_status` must be `PAID`, or the request is `ERR_ORDER_NOT_PAID` — this is the
    one direction in which the freight dimension is gated on the money dimension."
    PRD 3.6: "A payment smaller than the outstanding balance advances `UNPAID →
    PARTIALLY_PAID`; a payment exactly equal to the outstanding balance advances `UNPAID
    → PAID` or `PARTIALLY_PAID → PAID`, drives `balance_due_cents` to zero and stamps
    `paid_at` with the logical clock instant at which the balance first reached zero."
    PRD 3.6: "Finally, two deadlines are fixed from the order's `created_at`:
    `payment_due_at` is three days after creation and `pickup_deadline_at` is ten days
    after creation."

    Design: Difficulty/cross_entity_state_dependency/pickup_appointment_blocked_by_partially_paid_order
    """
    built = setup_fixed_price_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    pay_order(env, order, 148_500)

    part_paid = read_order(env, order["id"])
    assert part_paid["payment_status"] == "PARTIALLY_PAID"
    assert part_paid["balance_due_cents"] == 1_000_000
    assert part_paid["logistics_status"] == "AWAITING_APPOINTMENT"
    assert_instant(part_paid["pickup_deadline_at"], "2026-08-15T01:00:00Z")

    refused = _book(
        env,
        order,
        "2026-08-10T14:00:00Z",
        "2026-08-10T15:00:00Z",
        bol_number="BOL-PP1",
    )
    validate_error(refused, "ERR_ORDER_NOT_PAID", 409)

    assert total_count(
        api_client.list_pickup_appointments(ADMIN, {"sale_order_id": order["id"]})
    ) == 0
    unchanged = read_order(env, order["id"])
    assert unchanged["logistics_status"] == "AWAITING_APPOINTMENT"
    assert unchanged["amount_paid_cents"] == 148_500
    assert unchanged["payment_status"] == "PARTIALLY_PAID"


def test_settling_the_balance_admits_the_identical_booking_request():
    """Nothing about the window changed; only the parent order's payment dimension did,
    and that is enough to make the same request succeed.

    PRD 3.6: "Exactly two cross-dimension guards exist, and both are one-directional: an
    appointment may only be scheduled while `payment_status` is `PAID`, and a payment may
    not be accepted while `logistics_status` is `ABANDONED`."
    PRD 3.7: "An accepted booking advances the order `AWAITING_APPOINTMENT →
    APPOINTMENT_SCHEDULED` and advances the order's `version` by one."
    PRD 3.7: "The resulting `PickupAppointment` records its parent order through
    `sale_order_id`, begins with `appointment_status` `SCHEDULED`, `completed_at` null and
    `picked_up_unit_count` null, and carries the `dock_door_number` the platform assigns."

    Design: Difficulty/cross_entity_state_dependency/pickup_appointment_blocked_by_partially_paid_order
    """
    built = setup_fixed_price_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    pay_order(env, order, 148_500)

    refused = _book(
        env, order, "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z", bol_number="BOL-PP1"
    )
    validate_error(refused, "ERR_ORDER_NOT_PAID", 409)

    pay_order(env, order, 1_000_000)
    assert read_order(env, order["id"])["payment_status"] == "PAID"

    accepted = validate_success(
        _book(
            env,
            order,
            "2026-08-10T14:00:00Z",
            "2026-08-10T15:00:00Z",
            bol_number="BOL-PP1",
        ),
        201,
    )
    assert accepted["dock_door_number"] == 1
    assert accepted["appointment_status"] == "SCHEDULED"
    assert accepted["sale_order_id"] == order["id"]
    assert accepted["completed_at"] is None
    assert accepted["picked_up_unit_count"] is None
    assert read_order(env, order["id"])["logistics_status"] == "APPOINTMENT_SCHEDULED"


def test_the_deadline_failure_is_reported_ahead_of_the_door_collision():
    """The requested window is both too late for its own order and on top of the only
    door, and the earlier band must answer.

    PRD 3.7: "At band 12, the requested `window_end_at` must fall at or before the
    order's `pickup_deadline_at`, or the request is `ERR_PICKUP_DEADLINE_PASSED`; this
    deadline test runs **before** the door selector, so a request that could never be
    honoured in time is rejected on time rather than on capacity."
    PRD 2.5: "…the platform evaluates checks in sixteen numbered bands and returns the
    error belonging to the **lowest-numbered band** that fails, stopping there. Within
    the sequence, safety and identity questions come before time, time comes before
    physical capacity, and money comes last…"
    PRD 3.6: "Finally, two deadlines are fixed from the order's `created_at`:
    `payment_due_at` is three days after creation and `pickup_deadline_at` is ten days
    after creation."

    Design: Difficulty/priority_pair_validation_conflict/pickup_deadline_temporal_error_wins_over_dock_capacity
    """
    env = bootstrap_marketplace(warehouse_overrides=ONE_DOOR_WAREHOUSE)
    early = setup_paid_fixed_price_order(env)
    late = setup_paid_fixed_price_order(
        env, clock="2026-08-12T00:00:00Z",
        lot_overrides={"title": "Second overstock lot"},
    )
    order_b = read_order(env, early["order"]["id"])
    order_a = read_order(env, late["order"]["id"])
    assert_instant(order_b["pickup_deadline_at"], "2026-08-15T01:00:00Z")
    assert_instant(order_a["pickup_deadline_at"], "2026-08-22T00:00:00Z")

    held = book_appointment(
        env,
        order_a,
        window_start_at="2026-08-18T14:00:00Z",
        window_end_at="2026-08-18T15:00:00Z",
        bol_number="BOL-A1",
    )
    assert held["dock_door_number"] == 1

    conflicted = _book(
        env,
        order_b,
        "2026-08-18T14:30:00Z",
        "2026-08-18T15:30:00Z",
        bol_number="BOL-B1",
    )
    error = validate_error(conflicted, "ERR_PICKUP_DEADLINE_PASSED", 422)
    assert error["error_id"] != "ERR_DOCK_CAPACITY_EXHAUSTED"


def test_the_refused_late_booking_leaves_both_orders_exactly_as_they_were():
    """No half-built appointment is left behind, and the appointment that owns the door
    keeps it.

    PRD 3.7: "When no door is eligible the booking is rejected with
    `ERR_DOCK_CAPACITY_EXHAUSTED` and no appointment is created."
    PRD 3.7: "At band 9, the order's `logistics_status` must be `AWAITING_APPOINTMENT`,
    or the request is `ERR_ORDER_LOGISTICS_STATE_INVALID`. At band 10, the order's
    `payment_status` must be `PAID`, or the request is `ERR_ORDER_NOT_PAID` — this is the
    one direction in which the freight dimension is gated on the money dimension."
    PRD 3.7: "The new appointment is discoverable by listing pickup appointments filtered
    on the order."

    Design: Difficulty/priority_pair_validation_conflict/pickup_deadline_temporal_error_wins_over_dock_capacity
    """
    env = bootstrap_marketplace(warehouse_overrides=ONE_DOOR_WAREHOUSE)
    early = setup_paid_fixed_price_order(env)
    late = setup_paid_fixed_price_order(
        env, clock="2026-08-12T00:00:00Z",
        lot_overrides={"title": "Second overstock lot"},
    )
    order_b = read_order(env, early["order"]["id"])
    order_a = read_order(env, late["order"]["id"])
    held = book_appointment(
        env,
        order_a,
        window_start_at="2026-08-18T14:00:00Z",
        window_end_at="2026-08-18T15:00:00Z",
        bol_number="BOL-A1",
    )

    refused = _book(
        env, order_b, "2026-08-18T14:30:00Z", "2026-08-18T15:30:00Z", bol_number="BOL-B1"
    )
    validate_error(refused, "ERR_PICKUP_DEADLINE_PASSED", 422)

    assert total_count(
        api_client.list_pickup_appointments(ADMIN, {"sale_order_id": order_b["id"]})
    ) == 0
    reread_b = read_order(env, order_b["id"])
    assert reread_b["logistics_status"] == "AWAITING_APPOINTMENT"
    assert reread_b["payment_status"] == "PAID"

    kept = read_appointment(env, held["id"])
    assert kept["appointment_status"] == "SCHEDULED"
    assert kept["dock_door_number"] == 1


def test_a_window_ending_exactly_on_the_pickup_deadline_is_admitted():
    """One second past the deadline is refused; the boundary instant itself is inside the
    allowed range.

    PRD 3.7: "At band 12, the requested `window_end_at` must fall at or before the
    order's `pickup_deadline_at`, or the request is `ERR_PICKUP_DEADLINE_PASSED`; this
    deadline test runs **before** the door selector, so a request that could never be
    honoured in time is rejected on time rather than on capacity."
    PRD 3.7: "The resulting `PickupAppointment` records its parent order through
    `sale_order_id`, begins with `appointment_status` `SCHEDULED`, `completed_at` null and
    `picked_up_unit_count` null, and carries the `dock_door_number` the platform assigns."
    PRD 3.7: "An accepted booking advances the order `AWAITING_APPOINTMENT →
    APPOINTMENT_SCHEDULED` and advances the order's `version` by one."

    Design: Corner/validations/pickup_appointment_accepted_when_window_ends_exactly_at_the_deadline
    """
    built = setup_paid_auction_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    assert_instant(order["pickup_deadline_at"], "2026-08-22T00:00:00Z")
    assert order["payment_status"] == "PAID"

    one_second_late = _book(
        env,
        order,
        "2026-08-21T23:00:00Z",
        "2026-08-22T00:00:01Z",
        bol_number="BOL-LATE",
    )
    validate_error(one_second_late, "ERR_PICKUP_DEADLINE_PASSED", 422)
    assert read_order(env, order["id"])["logistics_status"] == "AWAITING_APPOINTMENT"

    on_the_boundary = validate_success(
        _book(
            env,
            order,
            "2026-08-21T23:00:00Z",
            "2026-08-22T00:00:00Z",
            bol_number="BOL-EDGE",
        ),
        201,
    )
    assert on_the_boundary["appointment_status"] == "SCHEDULED"
    assert on_the_boundary["dock_door_number"] == 1
    assert on_the_boundary["completed_at"] is None
    assert on_the_boundary["warehouse_id"] == env["warehouse"]["id"]
    assert on_the_boundary["carrier_id"] == env["carrier"]["id"]
    assert on_the_boundary["bol_number"] == "BOL-EDGE"

    scheduled = read_order(env, order["id"])
    assert scheduled["logistics_status"] == "APPOINTMENT_SCHEDULED"
    assert scheduled["picked_up_at"] is None


def test_collection_must_name_the_warehouse_the_lot_actually_sits_on():
    """A second, real warehouse is still the wrong warehouse, and the mismatch is
    reported as a mismatch rather than as a missing row.

    PRD 3.7: "Only then, at band 15, is the requested `warehouse_id` compared against the
    lot's own `warehouse_id`: goods can only be collected from the dock they sit on, and a
    mismatch is `ERR_WAREHOUSE_MISMATCH`."
    PRD 3.7: "The eligible doors are those numbers, from 1 through `dock_door_count`, on
    which no such conflict exists, and the platform assigns the **lowest-numbered**
    eligible door; no further tie-break is needed because door numbers are unique within a
    warehouse."

    Design: Corner/endpoints/pickup_appointment_rejected_when_warehouse_differs_from_the_lot_warehouse
    """
    env = bootstrap_marketplace()
    other_warehouse = create_warehouse(name="Reno DC", state_code="NV")
    built = setup_paid_fixed_price_order(env, lines=TWO_HUNDRED_UNIT_LINES)
    order = read_order(env, built["order"]["id"])

    wrong_dock = _book(
        env,
        order,
        "2026-08-10T09:00:00Z",
        "2026-08-10T10:00:00Z",
        bol_number="BOL-WRONG",
        warehouse_id=other_warehouse["id"],
    )
    validate_error(wrong_dock, "ERR_WAREHOUSE_MISMATCH", 422)
    assert read_order(env, order["id"])["logistics_status"] == "AWAITING_APPOINTMENT"
    assert total_count(
        api_client.list_pickup_appointments(ADMIN, {"sale_order_id": order["id"]})
    ) == 0

    right_dock = validate_success(
        _book(
            env,
            order,
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
            bol_number="BOL-RIGHT",
        ),
        201,
    )
    assert right_dock["warehouse_id"] == env["warehouse"]["id"]
    assert right_dock["dock_door_number"] == 1
    assert right_dock["appointment_status"] == "SCHEDULED"
    assert right_dock["sale_order_id"] == order["id"]
    assert right_dock["bol_number"] == "BOL-RIGHT"

    scheduled = read_order(env, order["id"])
    assert scheduled["logistics_status"] == "APPOINTMENT_SCHEDULED"
    assert scheduled["payment_status"] == "PAID"


def test_completion_is_barred_before_the_window_opens_and_after_it_has_run():
    """One second early is a timing error, the opening instant itself succeeds, and the
    completed appointment refuses both a repeat completion and a cancellation.

    PRD 3.7: "The appointment must be `SCHEDULED`, or the request is
    `ERR_APPOINTMENT_STATE_INVALID`, and the current logical clock must be at or after the
    appointment's `window_start_at`, or the request is `ERR_APPOINTMENT_NOT_STARTED`."
    PRD 3.7: "The appointment advances `SCHEDULED → COMPLETED` with `completed_at` stamped
    at the current logical clock and `picked_up_unit_count` recorded."
    PRD 3.7: "The order advances `APPOINTMENT_SCHEDULED → PICKED_UP`, stamps
    `picked_up_at`, receives the supplied `actual_freight_cents`, and sets
    `claim_window_closes_at` to five days after the completion instant — the window inside
    which the buyer may dispute the manifest."
    PRD 3.7: "**Cancelling an appointment.** A scheduled appointment may be cancelled,
    optionally with a `cancellation_reason`, by the owning `Buyer` or by `MarketplaceOps`.
    The appointment must be `SCHEDULED`."

    Design: Corner/errors/appointment_completion_errors_are_all_reachable
    """
    built = setup_paid_fixed_price_order(lines=TWO_HUNDRED_UNIT_LINES)
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    appointment = book_appointment(
        env,
        order,
        window_start_at="2026-08-10T09:00:00Z",
        window_end_at="2026-08-10T10:00:00Z",
        bol_number="BOL-COMP",
    )

    set_clock("2026-08-10T08:59:59Z")
    too_early = api_client.complete_pickup_appointment(
        appointment["id"], completion_payload(8_500, 200), env["dock_headers"]
    )
    validate_error(too_early, "ERR_APPOINTMENT_NOT_STARTED", 422)
    assert read_appointment(env, appointment["id"])["appointment_status"] == "SCHEDULED"

    set_clock("2026-08-10T09:00:00Z")
    completed = get_success_data(
        api_client.complete_pickup_appointment(
            appointment["id"], completion_payload(8_500, 200), env["dock_headers"]
        )
    )
    assert completed["appointment_status"] == "COMPLETED"
    assert_instant(completed["completed_at"], "2026-08-10T09:00:00Z")
    assert completed["picked_up_unit_count"] == 200

    picked_up = read_order(env, order["id"])
    assert picked_up["logistics_status"] == "PICKED_UP"
    assert picked_up["actual_freight_cents"] == 8_500
    assert picked_up["settlement_basis"] == "FINAL"
    assert picked_up["total_due_cents"] == 1_148_500
    assert picked_up["payment_status"] == "PAID"
    assert_instant(picked_up["claim_window_closes_at"], "2026-08-15T09:00:00Z")

    again = api_client.complete_pickup_appointment(
        appointment["id"], completion_payload(8_500, 200), env["dock_headers"]
    )
    validate_error(again, "ERR_APPOINTMENT_STATE_INVALID", 409)
    assert_instant(
        read_appointment(env, appointment["id"])["completed_at"], "2026-08-10T09:00:00Z"
    )

    cancelled = api_client.cancel_pickup_appointment(
        appointment["id"], {"cancellation_reason": "after the fact"}, env["dock_headers"]
    )
    validate_error(cancelled, "ERR_APPOINTMENT_STATE_INVALID", 409)
