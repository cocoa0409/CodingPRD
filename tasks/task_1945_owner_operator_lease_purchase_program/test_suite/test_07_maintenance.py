"""Maintenance: bay two-hour turnover buffer, warranty billing determination,
and work-order completion idempotency."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_active_lease, set_clock, create_service_bay, create_work_order,
    complete_work_order, create_work_order_payload,
)

ADMIN = TEST_USERS["lease_admin_headers"]
COORD = TEST_USERS["maintenance_coordinator_headers"]


# ─── Queue A: difficulty/resource_temporal_overlap ───

def _scenario_with_two_bay_bookings():
    """ACTIVE lease and a bay holding WO1 [08:00,10:00) and WO2 [12:00,13:00)
    on 2026-08-04 — a gap of exactly two hours between the windows."""
    scenario = create_active_lease()
    lease_id = scenario["lease"]["id"]
    bay = create_service_bay()
    wo1 = create_work_order(
        lease_id, bay["id"], category="PREVENTIVE", description="PM-A service",
        scheduled_start="2026-08-04T08:00:00Z", scheduled_end="2026-08-04T10:00:00Z",
        estimated_cost_cents=30000)
    wo2 = create_work_order(
        lease_id, bay["id"], category="REPAIR", description="Brake chamber",
        scheduled_start="2026-08-04T12:00:00Z", scheduled_end="2026-08-04T13:00:00Z",
        estimated_cost_cents=25000)
    scenario["bay"] = bay
    scenario["wo1"] = wo1
    scenario["wo2"] = wo2
    return scenario


def test_bay_two_hour_exact_gap_allowed(api):
    """PRD section 3.6: "against every existing booking of the same bay in `OPEN`
    or `COMPLETED` status (cancelled bookings free their windows), the new
    booking conflicts unless there is a gap of at least two hours between the
    windows on either side — that is, unless the new start is at or after the
    existing end plus two hours, or the new end is at or before the existing
    start minus two hours. A gap of exactly two hours is permitted; anything
    tighter is rejected with `ERR_BAY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bay_two_hour_buffer_semantics
    """
    scenario = _scenario_with_two_bay_bookings()
    assert scenario["wo1"]["status"] == "OPEN"
    assert scenario["wo2"]["status"] == "OPEN", (
        "booking at exactly a two-hour gap after WO1 was permitted")


def test_bay_thirty_minute_gap_rejected(api):
    """PRD section 3.6: "A gap of exactly two hours is permitted; anything
    tighter is rejected with `ERR_BAY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bay_two_hour_buffer_semantics
    """
    scenario = _scenario_with_two_bay_bookings()
    # 30 minutes after WO2's 13:00 end: tighter than the two-hour buffer.
    res = api.create_work_order(
        create_work_order_payload(
            scenario["lease"]["id"], scenario["bay"]["id"],
            category="REPAIR", description="Air line",
            scheduled_start="2026-08-04T13:30:00Z",
            scheduled_end="2026-08-04T14:30:00Z",
            estimated_cost_cents=15000), COORD)
    validate_error(res, ApiErrorId.ERR_BAY_WINDOW_CONFLICT.value)


# ─── Queue B: corner/calculations + corner/state_machines ──

def test_warranty_determination_four_way(api):
    """PRD section 3.6: "The billing rule: `RECALL` work is always
    `CARRIER`-billed; `PREVENTIVE` work is always `OPERATOR`-billed — preventive
    care is the operator's duty; `REPAIR` work is `WARRANTY`-billed when the
    `odometer_at_service` is at or below the truck's
    `powertrain_warranty_mileage_limit` and the `scheduled_start` is at or before
    the truck's `powertrain_warranty_expires_on` — both boundaries are inclusive
    — and `OPERATOR`-billed otherwise." PRD section 3.6: "raises the truck's
    `odometer_current` to the larger of its prior value and the service reading."

    Design: Corner/calculations/warranty_determination_four_way
    """
    scenario = create_active_lease(
        truck_overrides={"odometer_current": 90000,
                         "powertrain_warranty_expires_on": "2027-01-01",
                         "powertrain_warranty_mileage_limit": 100000})
    lease_id = scenario["lease"]["id"]
    bay = create_service_bay()
    # Four non-conflicting bookings on 2026-08-04, each pair gapped by 2 hours.
    wo1 = create_work_order(lease_id, bay["id"], category="REPAIR",
                            description="Injectors",
                            scheduled_start="2026-08-04T08:00:00Z",
                            scheduled_end="2026-08-04T09:00:00Z",
                            estimated_cost_cents=50000)
    wo2 = create_work_order(lease_id, bay["id"], category="REPAIR",
                            description="Transmission",
                            scheduled_start="2026-08-04T11:00:00Z",
                            scheduled_end="2026-08-04T12:00:00Z",
                            estimated_cost_cents=80000)
    wo3 = create_work_order(lease_id, bay["id"], category="PREVENTIVE",
                            description="Oil and filters",
                            scheduled_start="2026-08-04T14:00:00Z",
                            scheduled_end="2026-08-04T15:00:00Z",
                            estimated_cost_cents=12000)
    wo4 = create_work_order(lease_id, bay["id"], category="RECALL",
                            description="OEM recall campaign",
                            scheduled_start="2026-08-04T17:00:00Z",
                            scheduled_end="2026-08-04T18:00:00Z",
                            estimated_cost_cents=20000)
    set_clock("2026-08-05T09:00:00Z")

    b1 = complete_work_order(wo1["id"], 50000, 100000)
    assert b1["billed_to"] == "WARRANTY", "REPAIR at odometer == limit: inclusive boundary"
    b2 = complete_work_order(wo2["id"], 80000, 120000)
    assert b2["billed_to"] == "OPERATOR", "REPAIR above the mileage limit"
    b3 = complete_work_order(wo3["id"], 12000, 95000)
    assert b3["billed_to"] == "OPERATOR", "PREVENTIVE is always operator-billed"
    b4 = complete_work_order(wo4["id"], 20000, 96000)
    assert b4["billed_to"] == "CARRIER", "RECALL is always carrier-billed"

    truck = validate_success(api.get_truck(scenario["truck"]["id"], ADMIN), 200)
    assert truck["odometer_current"] == 120000, (
        "odometer raised to the max service reading; later lower readings do not regress it")


def test_work_order_complete_twice_rejected(api):
    """PRD section 3.6: "Completing or cancelling an order no longer `OPEN`
    fails with `ERR_WORK_ORDER_NOT_OPEN`."

    Design: Corner/state_machines/work_order_complete_twice_rejected
    """
    scenario = create_active_lease()
    bay = create_service_bay()
    wo = create_work_order(scenario["lease"]["id"], bay["id"], category="PREVENTIVE",
                           description="PM service",
                           scheduled_start="2026-08-04T08:00:00Z",
                           scheduled_end="2026-08-04T09:00:00Z",
                           estimated_cost_cents=10000)
    set_clock("2026-08-05T09:00:00Z")
    completed = complete_work_order(wo["id"], 10000, 70000)
    assert completed["status"] == "COMPLETED"

    res = api.complete_work_order(
        wo["id"], {"actual_cost_cents": 99999, "odometer_at_service": 71000}, COORD)
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_NOT_OPEN.value)

    after = validate_success(api.get_work_order(wo["id"], COORD), 200)
    assert after["status"] == "COMPLETED"
    assert after["actual_cost_cents"] == 10000, "first completion stands"
