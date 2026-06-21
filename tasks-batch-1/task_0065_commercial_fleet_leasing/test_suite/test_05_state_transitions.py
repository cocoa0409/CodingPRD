"""State-machine corner tests (queue B): invalid transitions, idempotency,
terminal lockdown, precondition enforcement, side effects. PRD §3.2, §3.6,
§3.7, §3.8.
"""
from test_helpers import (
    TEST_USERS,
    create_allocation_payload,
    get_success_data,
    read_vehicle,
    setup_active_lease,
    setup_assessed_repair,
    setup_scheduled_maintenance,
    setup_settlement_open,
    validate_error,
    validate_success,
)

FM = TEST_USERS["fleet_manager_headers"]
TG = TEST_USERS["telematics_gateway_headers"]


def test_lease_cancel_from_active_invalid_state(api):
    """PRD §3.2: "A draft lease that is not yet wanted can instead be
    cancelled — the `DRAFT` to `CANCELLED` transition."
    PRD §3.2: "Any lifecycle action attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    cancel is defined only from DRAFT; on an ACTIVE lease it is rejected.

    Design: Corner/state_machines/lease_cancel_from_active_returns_invalid_state
    """
    _, _, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    resp = api.cancel_lease(lease["id"], FM)
    validate_error(resp, "ERR_INVALID_STATE")
    assert get_success_data(api.get_lease(lease["id"], FM))["status"] == "ACTIVE"


def test_maintenance_complete_twice_invalid_state(api):
    """PRD §3.6: "Completing maintenance — the `IN_PROGRESS` to `COMPLETED`
    transition, permitted only from `IN_PROGRESS` — pins the order's
    `total_cost_cents` to the sum of its `labor_cents` and `parts_cents`."

    A second complete on an already-COMPLETED order is rejected; the pinned
    total_cost_cents is unchanged.

    Design: Corner/state_machines/maintenance_complete_twice_idempotency_returns_invalid_state
    """
    _, _, _, mo = setup_scheduled_maintenance(
        mo_overrides={"labor_cents": 5000, "parts_cents": 3000})
    get_success_data(api.start_maintenance(mo["id"], FM))
    get_success_data(api.complete_maintenance(mo["id"], FM))
    resp = api.complete_maintenance(mo["id"], FM)
    validate_error(resp, "ERR_INVALID_STATE")
    assert get_success_data(
        api.get_maintenance_order(mo["id"], FM))["total_cost_cents"] == 8000


def test_lease_terminal_closed_rejects_cancel(api):
    """PRD §3.2: "finalizing that settlement advances the lease from
    `PENDING_SETTLEMENT` to its terminal `CLOSED` state."
    PRD §3.2: "Any lifecycle action attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    A CLOSED lease rejects cancel.

    Design: Corner/state_machines/lease_terminal_closed_lockdown_rejects_cancel
    """
    _, _, lease, settlement = setup_settlement_open(
        driven_odometer=70000, harsh_events=0, idle_minutes=0)
    get_success_data(api.finalize_settlement(settlement["id"], FM))
    resp = api.cancel_lease(lease["id"], FM)
    validate_error(resp, "ERR_INVALID_STATE")
    assert get_success_data(api.get_lease(lease["id"], FM))["status"] == "CLOSED"


def test_initiate_return_blocked_by_assigned_allocation(api):
    """PRD §3.2: "which is permitted only from `ACTIVE` and only when no
    allocation on this lease is still `ASSIGNED`; a lingering assignment
    blocks return with `ERR_ACTIVE_ALLOCATION_EXISTS` (HTTP 409)."

    Design: Corner/state_machines/initiate_return_blocked_by_assigned_allocation
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="LIGHT_DUTY")
    driver = get_success_data(api.create_driver(
        {"lessee_id": lessee["id"], "full_name": "AA D", "license_number": "LIC-AA1"}, FM))
    get_success_data(api.create_allocation(
        create_allocation_payload(lease["id"], driver["id"], lease["version"]), FM))
    resp = api.initiate_return(lease["id"], FM)
    validate_error(resp, "ERR_ACTIVE_ALLOCATION_EXISTS")
    assert get_success_data(api.get_lease(lease["id"], FM))["status"] == "ACTIVE"


def test_approve_total_loss_estimate_rejected(api):
    """PRD §3.8: "Approval — the `ASSESSED` to `APPROVED` transition — is the
    not-a-total-loss path and is permitted only when the `estimate_cents` is
    at most eight-tenths of `insurance_cap_cents`; attempting to approve when
    the estimate exceeds that threshold is rejected with `ERR_IS_TOTAL_LOSS`
    (HTTP 409) because the claim must instead be declared a total loss."

    est=900000 > 0.8*1000000 → ERR_IS_TOTAL_LOSS.

    Design: Corner/state_machines/approve_total_loss_estimate_returns_is_total_loss
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=900000, insurance_cap_cents=1000000)
    resp = api.approve_repair(repair["id"], FM)
    validate_error(resp, "ERR_IS_TOTAL_LOSS")


def test_declare_total_loss_below_ratio_rejected(api):
    """PRD §3.8: "Declaring a total loss — the `ASSESSED` to `TOTAL_LOSS`
    transition — is the mirror path and is permitted only when the
    `estimate_cents` is strictly greater than eight-tenths of
    `insurance_cap_cents`; attempting to declare a total loss when the
    estimate is at or below that threshold is rejected with
    `ERR_NOT_TOTAL_LOSS` (HTTP 409)."

    est=300000 <= 0.8*800000=640000 → ERR_NOT_TOTAL_LOSS.

    Design: Corner/state_machines/declare_total_loss_below_ratio_returns_not_total_loss
    """
    _, _, _, repair = setup_assessed_repair(
        estimate_cents=300000, insurance_cap_cents=800000)
    resp = api.declare_total_loss(repair["id"], FM)
    validate_error(resp, "ERR_NOT_TOTAL_LOSS")


def test_total_loss_settle_charges_lessee_and_retires(api):
    """PRD §3.8: "On the total-loss branch, settling — the `TOTAL_LOSS` to
    `TOTAL_LOSS_SETTLED` transition, permitted only from `TOTAL_LOSS` — also
    runs the collision waterfall to pin the three allocations, adds the
    order's `lessee_responsible_cents` to the lessee's
    `outstanding_balance_cents`, decrements the vehicle's `open_block_count`
    by 1, and cascades the vehicle from `IN_REPAIR` to its terminal
    `RETIRED` state."

    INSURANCE_FIRST est=550000/cap=500000/ded=100000: insurance 500000,
    remainder 50000, deductible 50000, lessee_responsible 50000.

    Design: Corner/state_machines/total_loss_settle_waterfall_overflow_charges_lessee
    """
    lessee, vehicle, _, repair = setup_assessed_repair(
        estimate_cents=550000, insurance_cap_cents=500000,
        waterfall_model="INSURANCE_FIRST", collision_deductible_cents=100000)
    get_success_data(api.declare_total_loss(repair["id"], FM))
    data = validate_success(api.settle_total_loss(repair["id"], FM), 200)
    assert data["lessee_responsible_cents"] == 50000, data
    assert data["status"] == "TOTAL_LOSS_SETTLED", data
    assert read_vehicle(vehicle["id"])["status"] == "RETIRED"
    assert get_success_data(
        api.get_lessee(lessee["id"], FM))["outstanding_balance_cents"] == 50000


def test_initiate_return_freezes_fuel_cards(api):
    """PRD §3.2: "Initiating return captures the vehicle's current
    `odometer_miles` into the lease's `odometer_end`, freezes every
    still-`ACTIVE` fuel card on the lease (each cascading from `ACTIVE` to
    `FROZEN`), and increments the lease's `version` by 1."

    Design: Corner/state_machines/initiate_return_freezes_fuel_cards
    """
    lessee, vehicle, lease = setup_active_lease(vehicle_class="HEAVY_DUTY")
    card = get_success_data(api.create_fuel_card({"lease_id": lease["id"],
                                                  "card_number": "CARD-FF-1"}, FM))
    get_success_data(api.create_telematics_reading(
        {"vehicle_id": vehicle["id"], "jurisdiction": "CA", "odometer_miles": 70000,
         "segment_miles": 70000, "recorded_at": "2026-06-01T00:00:00Z"}, TG))
    data = validate_success(api.initiate_return(lease["id"], FM), 200)
    assert data["status"] == "RETURN_INITIATED", data
    assert get_success_data(api.get_fuel_card(card["id"], FM))["status"] == "FROZEN"
