"""State-machine and cascade depth tests (queue A): RepairOrder fork, Vehicle
maintenance cycle, transitive settlement cascade, maintenance-start block
cascade. PRD §3.2, §3.6, §3.7, §3.8.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    read_vehicle,
    setup_active_lease,
    setup_assessed_repair,
    setup_scheduled_maintenance,
    setup_settlement_open,
    validate_success,
)

FM = TEST_USERS["fleet_manager_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


# ===========================================================================
# non_linear_state_machine / repair_order_branch_assessed_to_approved_or_total_loss
# ===========================================================================

def test_repair_assessed_forks_to_total_loss(api):
    """PRD §3.8: "Declaring a total loss — the `ASSESSED` to `TOTAL_LOSS`
    transition — is the mirror path and is permitted only when the
    `estimate_cents` is strictly greater than eight-tenths of
    `insurance_cap_cents`."

    est=900000 > 0.8*1000000=800000 → total-loss branch is valid.

    Design: Difficulty/non_linear_state_machine/repair_order_branch_assessed_to_approved_or_total_loss
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=900000, insurance_cap_cents=1000000,
    )
    data = validate_success(api.declare_total_loss(repair["id"], FM), 200)
    assert data["status"] == "TOTAL_LOSS", data


def test_repair_assessed_forks_to_rejected(api):
    """PRD §3.8: "A claim in `ASSESSED` may also be rejected outright — the
    `ASSESSED` to `REJECTED` transition, permitted only from `ASSESSED` —
    which decrements the vehicle's `open_block_count` by 1 and moves the
    order to its terminal `REJECTED` state."

    A divergent branch from the same ASSESSED fork.

    Design: Difficulty/non_linear_state_machine/repair_order_branch_assessed_to_approved_or_total_loss
    """
    _, vehicle, _, repair = setup_assessed_repair(
        estimate_cents=100000, insurance_cap_cents=800000,
    )
    data = validate_success(api.reject_repair(repair["id"], FM), 200)
    assert data["status"] == "REJECTED", data
    assert read_vehicle(vehicle["id"])["open_block_count"] == 0


# ===========================================================================
# non_linear_state_machine / vehicle_cycles_allocated_to_in_maintenance_and_back
# ===========================================================================

def test_vehicle_returns_to_allocated_after_maintenance_complete(api):
    """PRD §3.6: "Completing maintenance — the `IN_PROGRESS` to `COMPLETED`
    transition, permitted only from `IN_PROGRESS` — pins the order's
    `total_cost_cents` to the sum of its `labor_cents` and `parts_cents`,
    decrements the vehicle's `open_block_count` by 1, and, only if that count
    has reached zero and the vehicle is currently `IN_MAINTENANCE`, cascades
    the vehicle from `IN_MAINTENANCE` back to `ALLOCATED`."

    labor 5000 + parts 3000 = total 8000; vehicle back to ALLOCATED.

    Design: Difficulty/non_linear_state_machine/vehicle_cycles_allocated_to_in_maintenance_and_back
    """
    _, vehicle, _, mo = setup_scheduled_maintenance(
        mo_overrides={"labor_cents": 5000, "parts_cents": 3000}
    )
    get_success_data(api.start_maintenance(mo["id"], FM))
    data = validate_success(api.complete_maintenance(mo["id"], FM), 200)
    assert data["total_cost_cents"] == 8000, data
    veh = read_vehicle(vehicle["id"])
    assert veh["status"] == "ALLOCATED", veh
    assert veh["open_block_count"] == 0, veh


def test_vehicle_enters_in_maintenance_on_start(api):
    """PRD §3.6: "Starting increments the vehicle's `open_block_count` by 1,
    and if the vehicle was `ALLOCATED` it cascades to `IN_MAINTENANCE`
    (a vehicle already `IN_MAINTENANCE` stays put)."

    The first leg of the ALLOCATED->IN_MAINTENANCE->ALLOCATED cycle.

    Design: Difficulty/non_linear_state_machine/vehicle_cycles_allocated_to_in_maintenance_and_back
    """
    _, vehicle, _, mo = setup_scheduled_maintenance()
    get_success_data(api.start_maintenance(mo["id"], FM))
    veh = read_vehicle(vehicle["id"])
    assert veh["status"] == "IN_MAINTENANCE", veh


# ===========================================================================
# transitive_cascade / settlement_finalize_cascades_lease_then_vehicle
# ===========================================================================

def test_settlement_finalize_cascades_to_closed_lease(api):
    """PRD §3.7: "Finalization pins all five computed figures (per the
    calculations below), adds the settlement's `net_charge_cents` to the
    lessee's `outstanding_balance_cents`, increments the settlement's
    `version` by 1, and cascades the lease from `PENDING_SETTLEMENT` to its
    terminal `CLOSED` state — which in turn cascades the vehicle from
    `ALLOCATED` back to `AVAILABLE`, making it eligible for the next
    customer."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascades_lease_then_vehicle
    """
    _, vehicle, lease, settlement = setup_settlement_open(driven_odometer=85000)
    data = validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert data["status"] == "FINALIZED", data
    assert get_success_data(api.get_lease(lease["id"], FM))["status"] == "CLOSED"


def test_settlement_finalize_frees_vehicle(api):
    """PRD §3.7: "...cascades the lease from `PENDING_SETTLEMENT` to its
    terminal `CLOSED` state — which in turn cascades the vehicle from
    `ALLOCATED` back to `AVAILABLE`, making it eligible for the next
    customer."

    The depth-3 tail: vehicle ends AVAILABLE.

    Design: Difficulty/transitive_cascade/settlement_finalize_cascades_lease_then_vehicle
    """
    _, vehicle, lease, settlement = setup_settlement_open(driven_odometer=85000)
    validate_success(api.finalize_settlement(settlement["id"], FM), 200)
    assert read_vehicle(vehicle["id"])["status"] == "AVAILABLE"


# ===========================================================================
# transitive_cascade / maintenance_start_increments_block_then_blocks_vehicle
# ===========================================================================

def test_maintenance_start_increments_block_count(api):
    """PRD §3.6: "Starting increments the vehicle's `open_block_count` by 1,
    and if the vehicle was `ALLOCATED` it cascades to `IN_MAINTENANCE`."

    open_block_count goes 0 -> 1.

    Design: Difficulty/transitive_cascade/maintenance_start_increments_block_then_blocks_vehicle
    """
    _, vehicle, _, mo = setup_scheduled_maintenance(
        vehicle_class="LIGHT_DUTY", mo_overrides={"kind": "CORRECTIVE"}
    )
    get_success_data(api.start_maintenance(mo["id"], FM))
    assert read_vehicle(vehicle["id"])["open_block_count"] == 1


def test_maintenance_start_blocks_vehicle_status(api):
    """PRD §3.6: "...if the vehicle was `ALLOCATED` it cascades to
    `IN_MAINTENANCE` (a vehicle already `IN_MAINTENANCE` stays put)."

    The increment from 0 drives ALLOCATED->IN_MAINTENANCE.

    Design: Difficulty/transitive_cascade/maintenance_start_increments_block_then_blocks_vehicle
    """
    _, vehicle, _, mo = setup_scheduled_maintenance(
        vehicle_class="LIGHT_DUTY", mo_overrides={"kind": "CORRECTIVE"}
    )
    get_success_data(api.start_maintenance(mo["id"], FM))
    assert read_vehicle(vehicle["id"])["status"] == "IN_MAINTENANCE"
