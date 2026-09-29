"""Will-call bay occupancy, the per-store sweep, and truck window scheduling."""

from datetime import datetime
from typing import Any, Dict, List

from test_helpers import (
    STORE_OPERATIONS,
    ApiErrorId,
    SKU_MORTAR_BAG,
    SKU_SHINGLE_BUNDLE,
    allocate_reservations,
    api_client,
    create_credit_line,
    create_delivery_appointment_payload,
    create_delivery_truck,
    create_will_call_staging_payload,
    get_success_data,
    read_pro_order,
    read_store_stock,
    set_clock,
    setup_account_at_tier,
    setup_reserved_order,
    setup_store_with_stock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant returned by the API, tolerating the Z suffix."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# Scenario builders (inlined: every test starts from an empty database)        #
# --------------------------------------------------------------------------- #


def _staged_will_call_order() -> Dict[str, Any]:
    """A 40-unit will-call order sitting STAGED in the store's single bay."""
    store, stocks = setup_store_with_stock(
        [(SKU_SHINGLE_BUNDLE, 600)], will_call_bay_slots=1, max_stage_hours=48
    )
    account = setup_account_at_tier(store["id"], "GOLD")
    create_credit_line(account["id"], limit_cents=100_000_000, terms_days=30)
    order, order_lines, reservations = setup_reserved_order(
        account["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 40)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )
    allocate_reservations(reservations)
    staging = get_success_data(
        api_client.create_will_call_staging(
            create_will_call_staging_payload(
                order["id"],
                store["id"],
                stage_start="2026-08-01T08:00:00Z",
                stage_hours=6,
            ),
            STORE_OPERATIONS,
        )
    )
    get_success_data(
        api_client.stage_will_call_staging(staging["id"], STORE_OPERATIONS)
    )
    return {
        "store": store,
        "stock": stocks[SKU_SHINGLE_BUNDLE],
        "account": account,
        "order": order,
        "order_lines": order_lines,
        "reservations": reservations,
        "staging": staging,
    }


def _single_bay_store_with_three_reserved_orders() -> Dict[str, Any]:
    """One store with a single will-call bay plus three reserved will-call orders."""
    store, stocks = setup_store_with_stock(
        [(SKU_MORTAR_BAG, 500)], will_call_bay_slots=1, max_stage_hours=48
    )
    account = setup_account_at_tier(store["id"], "MEMBER")
    orders = []
    for _ in range(3):
        order, _lines, _reservations = setup_reserved_order(
            account["id"],
            store["id"],
            [(SKU_MORTAR_BAG, 5)],
            payment_method="CARD",
            delivery_mode="WILL_CALL",
        )
        orders.append(order)
    return {
        "store": store,
        "stock": stocks[SKU_MORTAR_BAG],
        "account": account,
        "orders": orders,
    }


def _book_staging(order_id: str, store_id: str, stage_start: str, stage_hours: int):
    return api_client.create_will_call_staging(
        create_will_call_staging_payload(
            order_id, store_id, stage_start=stage_start, stage_hours=stage_hours
        ),
        STORE_OPERATIONS,
    )


def _reserved_delivery_orders(
    count: int,
    lift_gate_required: bool = False,
    store_id: str = None,
    account_id: str = None,
) -> List[Dict[str, Any]]:
    orders = []
    for _ in range(count):
        order, _lines, _reservations = setup_reserved_order(
            account_id,
            store_id,
            [(SKU_MORTAR_BAG, 5)],
            payment_method="CARD",
            delivery_mode="DELIVERY",
            lift_gate_required=lift_gate_required,
        )
        orders.append(order)
    return orders


def _one_truck_with_three_reserved_delivery_orders() -> Dict[str, Any]:
    """One 30-minute-buffer truck, three reserved delivery orders, first window booked."""
    store, _stocks = setup_store_with_stock([(SKU_MORTAR_BAG, 500)])
    truck = create_delivery_truck(
        store["id"],
        truck_code="T-1",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE", "DRIVEWAY"],
        turnaround_buffer_minutes=30,
    )
    account = setup_account_at_tier(store["id"], "MEMBER")
    orders = _reserved_delivery_orders(
        3, store_id=store["id"], account_id=account["id"]
    )
    first = get_success_data(
        api_client.create_delivery_appointment(
            create_delivery_appointment_payload(
                orders[0]["id"],
                truck["id"],
                window_start="2026-08-05T09:00:00Z",
                window_end="2026-08-05T11:00:00Z",
                jobsite_access_type="CURBSIDE",
            ),
            STORE_OPERATIONS,
        )
    )
    get_success_data(
        api_client.confirm_delivery_appointment(first["id"], STORE_OPERATIONS)
    )
    return {
        "store": store,
        "truck": truck,
        "account": account,
        "orders": orders,
        "first_appointment": first,
    }


def _two_trucks_one_lift_gate_order() -> Dict[str, Any]:
    """Two equally busy trucks — one lift-gate equipped, one not — and a lift-gate order."""
    store, _stocks = setup_store_with_stock(
        [(SKU_MORTAR_BAG, 500)], lift_gate_available=True
    )
    truck_with_lift_gate = create_delivery_truck(
        store["id"],
        truck_code="T-1",
        lift_gate_equipped=True,
        access_types_supported=["CURBSIDE"],
        turnaround_buffer_minutes=30,
    )
    truck_without_lift_gate = create_delivery_truck(
        store["id"],
        truck_code="T-2",
        lift_gate_equipped=False,
        access_types_supported=["CURBSIDE"],
        turnaround_buffer_minutes=30,
    )
    account = setup_account_at_tier(store["id"], "MEMBER")
    fillers = _reserved_delivery_orders(
        2, store_id=store["id"], account_id=account["id"]
    )
    for filler, truck in zip(fillers, (truck_without_lift_gate, truck_with_lift_gate)):
        appointment = get_success_data(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    filler["id"],
                    truck["id"],
                    window_start="2026-08-05T09:00:00Z",
                    window_end="2026-08-05T11:00:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            )
        )
        get_success_data(
            api_client.confirm_delivery_appointment(appointment["id"], STORE_OPERATIONS)
        )
    lift_gate_order = _reserved_delivery_orders(
        1, lift_gate_required=True, store_id=store["id"], account_id=account["id"]
    )[0]
    return {
        "store": store,
        "truck_with_lift_gate": truck_with_lift_gate,
        "truck_without_lift_gate": truck_without_lift_gate,
        "account": account,
        "lift_gate_order": lift_gate_order,
    }


# =========================================================================== #
# The per-store will-call sweep                                               #
# =========================================================================== #


class TestWillCallSweepCascade:
    def test_sweep_expires_lapsed_staging_and_releases_its_allocated_reservation(self):
        """PRD §3.8: "The sweep drives every staging at that store whose `expires_at` is at or before the current clock instant, and whose `status` is `SCHEDULED` or `STAGED`, to `EXPIRED`."
        PRD §3.8: "First, every reservation of the affected order in `HELD` or `ALLOCATED` is released with `released_reason_code` set to `STAGING_EXPIRED`."
        PRD §3.8: "The server computes `expires_at` as `stage_start` advanced by `stage_hours` hours."

        Design: Difficulty/transitive_cascade/will_call_sweep_expiry_cascades_release_stock_and_order_revert
        """
        scenario = _staged_will_call_order()
        staging = scenario["staging"]
        reservation = scenario["reservations"][0]
        assert _instant(staging["expires_at"]) == _instant("2026-08-01T14:00:00Z")

        set_clock("2026-08-01T14:00:00Z")
        validate_success(
            api_client.run_will_call_sweep(scenario["store"]["id"], STORE_OPERATIONS),
            expected_status=200,
        )

        swept_staging = validate_success(
            api_client.get_will_call_staging(staging["id"], STORE_OPERATIONS),
            expected_status=200,
        )
        assert swept_staging["status"] == "EXPIRED"

        released = validate_success(
            api_client.get_reservation(reservation["id"], STORE_OPERATIONS),
            expected_status=200,
        )
        assert released["status"] == "RELEASED"
        assert released["released_reason_code"] == "STAGING_EXPIRED"

    def test_sweep_restores_store_stock_and_reverts_the_order_to_submitted(self):
        """PRD §3.8: "Second, each of those releases recomputes `reserved_units` and `available_units` at the store that held the units."
        PRD §3.8: "Third, because every reservation of the order is now `RELEASED`, the order's `fulfillment_status` falls back from `RESERVED` or `STAGED` to `SUBMITTED` — the order survives, keeps its prices and its credit authorization, and can be sourced and staged again."
        PRD §3.7: "Consumption is the only operation in this API that reduces a store's `on_hand_units`: it decrements that figure by the reservation's `qty_units` and then recomputes `reserved_units` and `available_units` at that store, so the units leave both the on-hand base and the committed base in the same step."

        Design: Difficulty/transitive_cascade/will_call_sweep_expiry_cascades_release_stock_and_order_revert
        """
        scenario = _staged_will_call_order()
        stock_before = read_store_stock(scenario["stock"]["id"])
        assert stock_before["reserved_units"] == 40
        assert stock_before["available_units"] == 560

        set_clock("2026-08-01T14:00:00Z")
        validate_success(
            api_client.run_will_call_sweep(scenario["store"]["id"], STORE_OPERATIONS),
            expected_status=200,
        )

        stock_after = validate_success(
            api_client.get_store_stock(scenario["stock"]["id"], STORE_OPERATIONS),
            expected_status=200,
        )
        assert stock_after["reserved_units"] == 0
        assert stock_after["available_units"] == 600
        assert stock_after["on_hand_units"] == 600

        order = read_pro_order(scenario["order"]["id"], scenario["account"]["id"])
        assert order["fulfillment_status"] == "SUBMITTED"
        assert order["credit_status"] == "AUTHORIZED"


# =========================================================================== #
# Will-call bay capacity: half-open occupancy intervals                       #
# =========================================================================== #


class TestWillCallBayCapacity:
    def test_staging_starting_exactly_when_the_incumbent_expires_is_accepted(self):
        """PRD §3.8: "The server computes `expires_at` as `stage_start` advanced by `stage_hours` hours."
        PRD §3.8: "Because the interval is half-open, adjacency is not overlap: an existing staging whose `expires_at` is exactly the new staging's `stage_start` does not consume a bay against it, and back-to-back bookings pack perfectly."

        Design: Difficulty/resource_temporal_overlap/will_call_bay_adjacency_allowed_but_capacity_overlap_conflicts
        """
        scenario = _single_bay_store_with_three_reserved_orders()
        store_id = scenario["store"]["id"]
        orders = scenario["orders"]

        incumbent = validate_success(
            _book_staging(orders[0]["id"], store_id, "2026-08-02T08:00:00Z", 4),
            expected_status=201,
        )
        assert _instant(incumbent["expires_at"]) == _instant("2026-08-02T12:00:00Z")

        adjacent = validate_success(
            _book_staging(orders[1]["id"], store_id, "2026-08-02T12:00:00Z", 4),
            expected_status=201,
        )
        assert adjacent["status"] == "SCHEDULED"
        assert _instant(adjacent["stage_start"]) == _instant("2026-08-02T12:00:00Z")
        assert _instant(adjacent["expires_at"]) == _instant("2026-08-02T16:00:00Z")

    def test_staging_overlapping_the_only_bay_is_refused_as_capacity_full(self):
        """PRD §3.8: "And the store's bays must not be oversubscribed: **the occupancy interval is half-open, `[stage_start, expires_at)`**, and the booking is refused with `ERR_WILL_CALL_CAPACITY_FULL` when the new interval overlaps that of the store's `will_call_bay_slots` figure or more existing stagings in `SCHEDULED` or `STAGED`."

        Design: Difficulty/resource_temporal_overlap/will_call_bay_adjacency_allowed_but_capacity_overlap_conflicts
        """
        scenario = _single_bay_store_with_three_reserved_orders()
        store_id = scenario["store"]["id"]
        orders = scenario["orders"]

        validate_success(
            _book_staging(orders[0]["id"], store_id, "2026-08-02T08:00:00Z", 4),
            expected_status=201,
        )
        validate_success(
            _book_staging(orders[1]["id"], store_id, "2026-08-02T12:00:00Z", 4),
            expected_status=201,
        )

        validate_error(
            _book_staging(orders[2]["id"], store_id, "2026-08-02T11:00:00Z", 4),
            ApiErrorId.ERR_WILL_CALL_CAPACITY_FULL.value,
            expected_status=409,
        )

        at_store, _meta = validate_paginated(
            api_client.list_will_call_stagings(
                STORE_OPERATIONS, params={"store_id": store_id}
            )
        )
        assert len(at_store) == 2

        for_rejected_order, _meta = validate_paginated(
            api_client.list_will_call_stagings(
                STORE_OPERATIONS, params={"pro_order_id": orders[2]["id"]}
            )
        )
        assert len(for_rejected_order) == 0


# =========================================================================== #
# Truck windows: closed intervals inflated by the turnaround buffer           #
# =========================================================================== #


class TestTruckWindowBuffer:
    def test_fifteen_minute_gap_after_a_confirmed_window_is_a_truck_conflict(self):
        """PRD §3.8: "And the truck must be free, which is where the buffer bites: **the requested window is inflated by the truck's `turnaround_buffer_minutes` at both ends, and that inflated interval is closed at both endpoints** — the interval running from `window_start` less the buffer to `window_end` plus the buffer, inclusive of both."
        PRD §3.8: "If that inflated interval intersects the window of any `SCHEDULED` or `CONFIRMED` appointment of the same truck, the booking is refused with `ERR_TRUCK_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/truck_buffer_turns_gap_into_conflict
        """
        scenario = _one_truck_with_three_reserved_delivery_orders()
        second_order = scenario["orders"][1]

        validate_error(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    second_order["id"],
                    scenario["truck"]["id"],
                    window_start="2026-08-05T11:15:00Z",
                    window_end="2026-08-05T12:15:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value,
            expected_status=409,
        )

        rows, _meta = validate_paginated(
            api_client.list_delivery_appointments(
                STORE_OPERATIONS, params={"pro_order_id": second_order["id"]}
            )
        )
        assert len(rows) == 0

    def test_forty_five_minute_gap_clears_the_buffer_and_books_the_truck(self):
        """PRD §3.1: "`turnaround_buffer_minutes`, a non-negative integer defaulting to 30, is the depot padding the scheduler applies on **both** sides of every appointment window when it tests whether the truck is already committed."
        PRD §3.8: "Because the inflated interval is closed, touching at a single instant counts as an intersection: two appointments on the same truck must be separated by strictly more than the buffer, and a second booking that begins exactly one buffer-length after the first one ends is a conflict."
        PRD §3.8: "A new appointment starts at `status` `SCHEDULED` with `delivered_at` and `cancel_reason_code` null, and immediately occupies the buffered window against later bookings."

        Design: Difficulty/resource_temporal_overlap/truck_buffer_turns_gap_into_conflict
        """
        scenario = _one_truck_with_three_reserved_delivery_orders()
        truck_id = scenario["truck"]["id"]

        validate_error(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    scenario["orders"][1]["id"],
                    truck_id,
                    window_start="2026-08-05T11:15:00Z",
                    window_end="2026-08-05T12:15:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value,
            expected_status=409,
        )

        booked = validate_success(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    scenario["orders"][2]["id"],
                    truck_id,
                    window_start="2026-08-05T11:45:00Z",
                    window_end="2026-08-05T12:45:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            expected_status=201,
        )
        assert booked["status"] == "SCHEDULED"
        assert _instant(booked["window_start"]) == _instant("2026-08-05T11:45:00Z")

        incumbent = validate_success(
            api_client.get_delivery_appointment(
                scenario["first_appointment"]["id"], STORE_OPERATIONS
            ),
            expected_status=200,
        )
        assert incumbent["status"] == "CONFIRMED"

        on_truck, _meta = validate_paginated(
            api_client.list_delivery_appointments(
                STORE_OPERATIONS, params={"delivery_truck_id": truck_id}
            )
        )
        assert len(on_truck) == 2


# =========================================================================== #
# Lift-gate capability is checked ahead of the truck window conflict          #
# =========================================================================== #


class TestLiftGateOutranksTruckWindow:
    def test_missing_lift_gate_is_reported_ahead_of_the_truck_window_conflict(self):
        """PRD §2.11: "When a single request could fail several checks, the server must report the failure that comes first in the following ladder."
        PRD §2.11: "**Lift-gate capability** — when the order requires a lift gate, the assigned truck's `lift_gate_equipped` is true **and** the dispatching store's `lift_gate_available` is true, otherwise `ERR_LIFT_GATE_UNAVAILABLE`."
        PRD §2.11: "**Truck window conflict** — the buffered window does not intersect another live appointment on the same truck, otherwise `ERR_TRUCK_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/lift_gate_safety_outranks_truck_window_constraint
        """
        scenario = _two_trucks_one_lift_gate_order()
        order = scenario["lift_gate_order"]

        error = validate_error(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order["id"],
                    scenario["truck_without_lift_gate"]["id"],
                    window_start="2026-08-05T11:15:00Z",
                    window_end="2026-08-05T12:15:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            ApiErrorId.ERR_LIFT_GATE_UNAVAILABLE.value,
            expected_status=422,
        )
        assert error["error_id"] != ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value

        rows, _meta = validate_paginated(
            api_client.list_delivery_appointments(
                STORE_OPERATIONS, params={"pro_order_id": order["id"]}
            )
        )
        assert len(rows) == 0

        stored_order = read_pro_order(order["id"], scenario["account"]["id"])
        assert stored_order["fulfillment_status"] == "RESERVED"

    def test_same_window_on_a_lift_gate_truck_still_reports_the_window_conflict(self):
        """PRD §3.8: "An order whose `lift_gate_required` is true demands both that the truck's `lift_gate_equipped` is true and that the store's `lift_gate_available` is true — both sides, the equipment and the yard capability — otherwise `ERR_LIFT_GATE_UNAVAILABLE`."
        PRD §3.8: "If that inflated interval intersects the window of any `SCHEDULED` or `CONFIRMED` appointment of the same truck, the booking is refused with `ERR_TRUCK_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/lift_gate_safety_outranks_truck_window_constraint
        """
        scenario = _two_trucks_one_lift_gate_order()
        order = scenario["lift_gate_order"]

        validate_error(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order["id"],
                    scenario["truck_without_lift_gate"]["id"],
                    window_start="2026-08-05T11:15:00Z",
                    window_end="2026-08-05T12:15:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            ApiErrorId.ERR_LIFT_GATE_UNAVAILABLE.value,
            expected_status=422,
        )

        validate_error(
            api_client.create_delivery_appointment(
                create_delivery_appointment_payload(
                    order["id"],
                    scenario["truck_with_lift_gate"]["id"],
                    window_start="2026-08-05T11:15:00Z",
                    window_end="2026-08-05T12:15:00Z",
                    jobsite_access_type="CURBSIDE",
                ),
                STORE_OPERATIONS,
            ),
            ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value,
            expected_status=409,
        )

        rows, _meta = validate_paginated(
            api_client.list_delivery_appointments(
                STORE_OPERATIONS, params={"pro_order_id": order["id"]}
            )
        )
        assert len(rows) == 0

        stored_order = read_pro_order(order["id"], scenario["account"]["id"])
        assert stored_order["fulfillment_status"] == "RESERVED"
