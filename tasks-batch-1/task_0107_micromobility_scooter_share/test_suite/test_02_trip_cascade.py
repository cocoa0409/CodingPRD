"""The trip-end cascade and its conserved-quantity invariants: the depth-3
charge/fine/debit chain in a NO_PARK zone, the depth-2 low-battery -> swap-task
chain, the money-conserving fine-charge/waive-refund cycle, and the fleet-
headcount-conserving swap completion.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    make_rider_headers,
    make_technician_headers,
    TEST_USERS,
    fixtures as fx,
)

_ADMIN = TEST_USERS["admin_headers"]


def test_no_park_end_charges_fines_and_debits_wallet(api):
    """PRD §3.5: "First, the wallet is charged: a `WalletTransaction` of type
    `TRIP_CHARGE` is created carrying the negative `final_fare_cents`, and
    `Rider.wallet_balance_cents` is reduced by the final fare."
    PRD §3.5: "Third, raising that fine immediately charges the wallet again: a
    `WalletTransaction` of type `FINE_CHARGE` is created carrying the negative fine
    `amount_cents`, `Rider.wallet_balance_cents` is reduced by the fine amount, and
    `Rider.outstanding_fine_cents` is increased by the fine amount."

    Wallet 5000, trip 90s => 2 min => fare 160; NO_PARK fine 2500.
    Final wallet = 5000 - 160 - 2500 = 2340; outstanding = 2500.

    Design: Difficulty/transitive_cascade/trip_end_in_no_park_charges_then_fines_then_debits_wallet
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-06T00:00:00Z", "2026-06-06T00:01:30Z", amount_cents=5000)
    assert trip["final_fare_cents"] == 160, f"expected 160, got {trip['final_fare_cents']}"
    assert fine["reason"] == "BAD_PARKING_NO_PARK"
    assert fine["amount_cents"] == 2500
    rider_after = validate_success(api.get_rider(rider["id"], make_rider_headers(rider["id"])))
    assert rider_after["wallet_balance_cents"] == 2340, (
        f"expected wallet 2340, got {rider_after['wallet_balance_cents']}")
    assert rider_after["outstanding_fine_cents"] == 2500, (
        f"expected outstanding 2500, got {rider_after['outstanding_fine_cents']}")


def test_no_park_end_fine_charge_wallet_transaction_exists(api):
    """PRD §3.5: "Third, raising that fine immediately charges the wallet again: a
    `WalletTransaction` of type `FINE_CHARGE` is created carrying the negative fine
    `amount_cents`, `Rider.wallet_balance_cents` is reduced by the fine amount, and
    `Rider.outstanding_fine_cents` is increased by the fine amount."

    The depth-3 link is observable as a FINE_CHARGE ledger row of -2500 for the
    fine raised by the trip's end.

    Design: Difficulty/transitive_cascade/trip_end_in_no_park_charges_then_fines_then_debits_wallet
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-06T00:00:00Z", "2026-06-06T00:01:30Z", amount_cents=5000)
    data, meta = validate_paginated(api.list_wallet_transactions(_ADMIN, params={"fine_id": fine["id"]}))
    assert meta["total_count"] == 1, f"expected one FINE_CHARGE, got {meta['total_count']}"
    assert data[0]["txn_type"] == "FINE_CHARGE"
    assert data[0]["amount_cents"] == -2500, f"expected -2500, got {data[0]['amount_cents']}"


def test_low_battery_end_revives_then_opens_swap_task(api):
    """PRD §3.5: "Finally, the vehicle leaves use: its `current_zone_id` is set to
    the trip's `end_zone_id`, and if its `battery_pct` is at least 20 it transitions
    `IN_USE → AVAILABLE`, while if its `battery_pct` is below 20 it transitions
    `IN_USE → LOW_BATTERY`."
    PRD §3.5: "A vehicle that lands in `LOW_BATTERY` automatically spawns a
    battery-swap `RebalancingTask` for itself — a task with `task_type` `SWAP`, a
    null `target_zone_id` and null `technician_id`, status `OPEN`, a `window_start`
    of the current clock, and a `window_end` one hour (3,600 seconds) later."

    Battery forced to 10 before end => vehicle LOW_BATTERY and exactly one OPEN
    SWAP task for it.

    Design: Difficulty/transitive_cascade/trip_end_low_battery_revives_vehicle_then_opens_swap_task
    """
    plan, zone, vehicle, rider, trip, swap_task = fx.setup_low_battery_swap_task(
        "2026-06-06T10:00:00Z", "2026-06-06T10:01:30Z")
    veh_after = validate_success(api.get_vehicle(vehicle["id"], _ADMIN))
    assert veh_after["status"] == "LOW_BATTERY", (
        f"expected LOW_BATTERY, got {veh_after['status']}")
    data, meta = validate_paginated(
        api.list_rebalancing_tasks(_ADMIN, params={"vehicle_id": vehicle["id"]}))
    assert meta["total_count"] == 1, f"expected exactly one task, got {meta['total_count']}"
    assert data[0]["task_type"] == "SWAP", f"expected SWAP, got {data[0]['task_type']}"
    assert data[0]["status"] == "OPEN", f"expected OPEN, got {data[0]['status']}"


def test_low_battery_end_vehicle_status_is_low_battery(api):
    """PRD §3.5: "if its `battery_pct` is below 20 it transitions
    `IN_USE → LOW_BATTERY`."

    A trip ended with the vehicle's battery at 10 (below 20) lands the vehicle in
    LOW_BATTERY rather than AVAILABLE.

    Design: Difficulty/transitive_cascade/trip_end_low_battery_revives_vehicle_then_opens_swap_task
    """
    plan, zone, vehicle, rider, trip, swap_task = fx.setup_low_battery_swap_task(
        "2026-06-06T10:00:00Z", "2026-06-06T10:01:30Z")
    veh_after = validate_success(api.get_vehicle(vehicle["id"], _ADMIN))
    assert veh_after["status"] == "LOW_BATTERY"


def test_fine_charge_then_waive_refund_conserves_wallet(api):
    """PRD §3.6: "Waiving the fine instead transitions it `DISPUTED → WAIVED`,
    which is terminal, and reverses the original charge: a `WalletTransaction` of
    type `FINE_REFUND` is created carrying the positive `amount_cents`,
    `Rider.wallet_balance_cents` is increased by the fine amount, and
    `Rider.outstanding_fine_cents` is reduced by the fine amount."

    Wallet 5000, trip fare 160, fine 2500 charged then waived: the FINE_CHARGE and
    FINE_REFUND net to 0, so wallet == 5000 - 160 == 4840 and outstanding == 0.

    Design: Difficulty/compensating_invariant/fine_charge_then_waive_refund_conserves_wallet_money
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-14T00:00:00Z", "2026-06-14T00:01:30Z", amount_cents=5000)
    headers = make_rider_headers(rider["id"])
    validate_success(api.dispute_fine(fine["id"], headers))
    validate_success(api.waive_fine(fine["id"], _ADMIN))
    rider_after = validate_success(api.get_rider(rider["id"], headers))
    assert rider_after["wallet_balance_cents"] == 4840, (
        f"expected 4840, got {rider_after['wallet_balance_cents']}")
    assert rider_after["outstanding_fine_cents"] == 0, (
        f"expected outstanding 0, got {rider_after['outstanding_fine_cents']}")


def test_waive_creates_fine_refund_ledger_entry(api):
    """PRD §3.6: "Waiving the fine instead transitions it `DISPUTED → WAIVED`,
    which is terminal, and reverses the original charge: a `WalletTransaction` of
    type `FINE_REFUND` is created carrying the positive `amount_cents`,
    `Rider.wallet_balance_cents` is increased by the fine amount, and
    `Rider.outstanding_fine_cents` is reduced by the fine amount."

    The signed sum of the FINE_CHARGE (-2500) and FINE_REFUND (+2500) ledger rows
    for the fine is 0.

    Design: Difficulty/compensating_invariant/fine_charge_then_waive_refund_conserves_wallet_money
    """
    plan, ok_zone, np_zone, vehicle, rider, trip, fine = fx.setup_trip_ended_in_no_park(
        "2026-06-14T00:00:00Z", "2026-06-14T00:01:30Z", amount_cents=5000)
    headers = make_rider_headers(rider["id"])
    validate_success(api.dispute_fine(fine["id"], headers))
    validate_success(api.waive_fine(fine["id"], _ADMIN))
    data, meta = validate_paginated(api.list_wallet_transactions(_ADMIN, params={"fine_id": fine["id"]}))
    by_type = {row["txn_type"]: row["amount_cents"] for row in data}
    assert by_type.get("FINE_CHARGE") == -2500, f"FINE_CHARGE expected -2500, got {by_type}"
    assert by_type.get("FINE_REFUND") == 2500, f"FINE_REFUND expected +2500, got {by_type}"
    assert by_type["FINE_CHARGE"] + by_type["FINE_REFUND"] == 0


def test_swap_completion_conserves_fleet_headcount(api):
    """PRD §3.7: "For a `SWAP`, the referenced vehicle must currently be
    `LOW_BATTERY`; completion recharges it by setting `battery_pct` to 100 and
    transitions the vehicle `LOW_BATTERY → AVAILABLE`."

    Two vehicles registered. The scooter goes LOW_BATTERY on trip end, the auto
    SWAP task is assigned and completed: the vehicle returns AVAILABLE with battery
    100, and the total vehicle count is unchanged (2 before and after).

    Design: Difficulty/compensating_invariant/swap_task_completion_conserves_fleet_headcount
    """
    zone = fx.create_zone(zone_type="RIDE_OK", priority=5)
    technician = fx.create_technician(zone["id"], name="Tech U")
    fx.create_vehicle(zone["id"], vehicle_type="EBIKE", qr_code="QR-R1", battery_pct=100)
    scooter = fx.create_vehicle(zone["id"], vehicle_type="SCOOTER", qr_code="QR-R2", battery_pct=20)

    _, meta_before = validate_paginated(api.list_vehicles(_ADMIN))
    total_before = meta_before["total_count"]
    assert total_before == 2, f"expected 2 vehicles before, got {total_before}"

    plan = fx.create_standard_plan()
    rider = fx.create_funded_rider(plan["id"])
    trip = fx.start_trip(rider, scooter, "2026-06-15T10:00:00Z")
    fx.set_battery(scooter["id"], 10)
    fx.end_trip(rider, trip, zone["id"], "2026-06-15T10:01:30Z")

    tasks, _ = validate_paginated(
        api.list_rebalancing_tasks(_ADMIN, params={"vehicle_id": scooter["id"]}))
    task = tasks[0]
    fx.assign_task(task, technician)
    tech_headers = make_technician_headers(technician["id"])
    validate_success(api.complete_rebalancing_task(task["id"], tech_headers))

    veh_after = validate_success(api.get_vehicle(scooter["id"], _ADMIN))
    assert veh_after["status"] == "AVAILABLE", f"expected AVAILABLE, got {veh_after['status']}"
    assert veh_after["battery_pct"] == 100, f"expected battery 100, got {veh_after['battery_pct']}"

    _, meta_after = validate_paginated(api.list_vehicles(_ADMIN))
    assert meta_after["total_count"] == 2, (
        f"fleet headcount changed: before {total_before}, after {meta_after['total_count']}")


def test_swap_completion_recharges_battery_to_full(api):
    """PRD §3.7: "For a `SWAP`, the referenced vehicle must currently be
    `LOW_BATTERY`; completion recharges it by setting `battery_pct` to 100 and
    transitions the vehicle `LOW_BATTERY → AVAILABLE`."
    PRD §3.7: "Either completion transitions the task to `COMPLETED`."

    The forward action (LOW_BATTERY) and its completion (AVAILABLE, battery 100)
    leave the same vehicle in place — never destroyed or duplicated. Completing the
    SWAP both recharges the vehicle to 100 and moves the task to COMPLETED.

    Design: Difficulty/compensating_invariant/swap_task_completion_conserves_fleet_headcount
    """
    plan, zone, vehicle, rider, trip, swap_task = fx.setup_low_battery_swap_task(
        "2026-06-15T10:00:00Z", "2026-06-15T10:01:30Z")
    technician = fx.create_technician(zone["id"], name="Tech U2")
    fx.assign_task(swap_task, technician)
    tech_headers = make_technician_headers(technician["id"])
    completed = validate_success(api.complete_rebalancing_task(swap_task["id"], tech_headers))
    assert completed["status"] == "COMPLETED", f"expected COMPLETED, got {completed['status']}"
    veh_after = validate_success(api.get_vehicle(vehicle["id"], _ADMIN))
    assert veh_after["battery_pct"] == 100, f"expected battery 100, got {veh_after['battery_pct']}"
    assert veh_after["status"] == "AVAILABLE", f"expected AVAILABLE, got {veh_after['status']}"
