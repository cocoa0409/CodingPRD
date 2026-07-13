"""Accident report cascade: vehicle sidelined -> future reservation cancelled -> budget released."""
from test_helpers import (
    validate_success,
    create_policy, create_department, create_pool_vehicle,
    create_confirmed_reservation, set_clock, get_department, get_vehicle,
    create_accident_claim_payload, TEST_USERS,
)

CLERK = TEST_USERS["motor_pool_clerk_headers"]
FIN = TEST_USERS["finance_officer_headers"]


def _setup_confirmed_future_reservation(api):
    create_policy()
    set_clock("2026-06-01T00:00:00Z")
    dep = create_department()
    vehicle = create_pool_vehicle(vin="VIN-CAS-1")
    reservation = create_confirmed_reservation(
        dep["id"], requested_start="2026-06-20T09:00:00Z",
        requested_end="2026-06-20T13:00:00Z")
    assert get_department(dep["id"])["committed_budget_cents"] == 6000
    return dep, vehicle, reservation


def test_at_fault_accident_sidelines_vehicle_and_cancels_reservation(api):
    """PRD §3.6: "when the driver is at fault, or the estimated_damage_cents is at least
    500,000, the vehicle is sidelined — its operational_status moves to OUT_OF_SERVICE,
    and every reservation assigned to that vehicle that is currently CONFIRMED with a
    requested_start still in the future relative to the clock is cancelled".

    Design: Difficulty/transitive_cascade/accident_out_of_service_cancels_reservation_releases_budget
    """
    dep, vehicle, reservation = _setup_confirmed_future_reservation(api)
    validate_success(api.create_accident_claim(
        create_accident_claim_payload(vehicle["id"], reported_at="2026-06-02T00:00:00Z",
                                      at_fault=True, estimated_damage_cents=800000), FIN), 201)
    assert get_vehicle(vehicle["id"])["operational_status"] == "OUT_OF_SERVICE"
    assert validate_success(api.get_reservation(reservation["id"], CLERK), 200)["status"] == "CANCELLED"


def test_at_fault_accident_releases_committed_budget(api):
    """PRD §3.6: "for each such cancelled reservation the department's
    committed_budget_cents is reduced by that reservation's estimated_cost_cents."

    Design: Difficulty/transitive_cascade/accident_out_of_service_cancels_reservation_releases_budget
    """
    dep, vehicle, reservation = _setup_confirmed_future_reservation(api)
    validate_success(api.create_accident_claim(
        create_accident_claim_payload(vehicle["id"], reported_at="2026-06-02T00:00:00Z",
                                      at_fault=True, estimated_damage_cents=800000), FIN), 201)
    assert get_department(dep["id"])["committed_budget_cents"] == 0
