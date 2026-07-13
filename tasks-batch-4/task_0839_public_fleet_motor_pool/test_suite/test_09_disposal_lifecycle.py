"""Disposal/auction lifecycle: state legality, reserve floor, safety gate, OCC, sale cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_policy, set_clock, create_department, create_pool_vehicle, create_shop_bay,
    create_flagged_vehicle, list_vehicle_for_disposal, create_bidding_disposal,
    get_vehicle, get_vehicle_version, get_department,
    create_disposal_payload, create_accident_claim_payload, create_work_order_payload,
    create_fuel_log_payload, TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
TECH = TEST_USERS["shop_tech_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# ─── state_machines / sell_disposal_not_in_bidding_returns_invalid_state ───

def test_sell_disposal_not_in_bidding_returns_invalid_state(api):
    """PRD §3.5: "A sale is permitted only from BIDDING, and the hammer price must be at
    least the record's reserve_price_cents".

    Design: Corner/state_machines/sell_disposal_not_in_bidding_returns_invalid_state
    """
    vehicle = create_flagged_vehicle()
    disposal = list_vehicle_for_disposal(vehicle["id"], reserve_price_cents=100000)
    res = api.sell_disposal(disposal["id"], {"sale_price_cents": 200000, "buyer_name": "Bidder"}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


# ─── validations / sell_below_reserve_returns_below_reserve ───

def test_sell_below_reserve_returns_below_reserve(api):
    """PRD §3.5: "a price below reserve is rejected with ERR_BELOW_RESERVE."

    Design: Corner/validations/sell_below_reserve_returns_below_reserve
    """
    vehicle = create_flagged_vehicle()
    disposal = create_bidding_disposal(vehicle["id"], reserve_price_cents=100000)
    res = api.sell_disposal(disposal["id"], {"sale_price_cents": 90000, "buyer_name": "Low"}, ADMIN)
    validate_error(res, "ERR_BELOW_RESERVE")


# ─── validations / disposal_blocked_by_open_accident ───

def test_disposal_blocked_by_open_accident(api):
    """PRD §3.5: "the vehicle may not have any open accident and may not be IN_SHOP — if
    open_accident_count is greater than zero or operational_status is IN_SHOP, listing is
    rejected with ERR_DISPOSAL_BLOCKED."

    Design: Corner/validations/disposal_blocked_by_open_accident
    """
    vehicle = create_flagged_vehicle()
    validate_success(api.create_accident_claim(
        create_accident_claim_payload(vehicle["id"], reported_at="2026-05-05T00:00:00Z",
                                      at_fault=False, estimated_damage_cents=10000,
                                      third_party_liable_pct=0.5), FIN), 201)
    version = get_vehicle_version(vehicle["id"])  # fresh, so OCC passes and safety gate fires
    res = api.create_disposal(vehicle["id"], create_disposal_payload(version, reserve_price_cents=100000), ADMIN)
    validate_error(res, "ERR_DISPOSAL_BLOCKED")


# ─── cross_cutting_complexity_layers / stale_vehicle_version_on_disposal_create ───

def test_stale_vehicle_version_on_disposal_create(api):
    """PRD §2.6: "its request must carry expected_vehicle_version holding the client's
    last-observed version of that vehicle."
    PRD §2.6: "If that value does not equal the vehicle's current version — because
    another writer has advanced the vehicle since the client last read it (for example, a
    concurrent relist or lifecycle change) — the create is rejected with
    ERR_STALE_VEHICLE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_vehicle_version_on_disposal_create
    """
    vehicle = create_flagged_vehicle()
    version = get_vehicle_version(vehicle["id"])
    res = api.create_disposal(
        vehicle["id"], create_disposal_payload(version - 1, reserve_price_cents=100000), ADMIN)
    validate_error(res, "ERR_STALE_VEHICLE_VERSION")


# ─── cross_cutting_complexity_layers / disposal_sell_credits_department_billed_ytd ───

def test_disposal_sell_credits_department_billed_ytd(api):
    """PRD §3.5: "The commission_cents is the sale price multiplied by that rate, rounded
    half up. The net_proceeds_cents is the sale price minus the commission minus the
    reconditioning_cost_cents". PRD §3.5: "If the vehicle was dedicated to a department
    (its assigned_department_id is not null), the net proceeds are credited to that
    department by subtracting net_proceeds_cents from its billed_ytd_cents."

    Design: Corner/cross_cutting_complexity_layers/disposal_sell_credits_department_billed_ytd
    """
    create_policy()
    set_clock("2026-06-01T00:00:00Z")
    dep = create_department(cost_center_code="CC-D1")
    vehicle = create_pool_vehicle(vin="VIN-SELL-1", in_service_date="2010-01-01T00:00:00Z",
                                  acquisition_cost_cents=2000000)
    validate_success(api.assign_vehicle(
        vehicle["id"],
        {"assignment_type": "DEPARTMENT_ASSIGNED", "assigned_department_id": dep["id"]}, ADMIN), 200)
    get_success_data(api.create_fuel_log(
        vehicle["id"],
        create_fuel_log_payload(reading_at="2026-06-01T06:00:00Z", gallons=1,
                                fuel_cost_cents=0, odometer_miles=150000), TECH))
    validate_success(api.evaluate_replacement(vehicle["id"], ADMIN), 200)
    version = get_vehicle_version(vehicle["id"])
    disposal = get_success_data(api.create_disposal(
        vehicle["id"], create_disposal_payload(version, reserve_price_cents=100000), ADMIN))
    validate_success(api.open_bidding(disposal["id"], ADMIN), 200)
    sold = validate_success(api.sell_disposal(
        disposal["id"], {"sale_price_cents": 1000000, "buyer_name": "Winner"}, ADMIN), 200)
    assert sold["commission_cents"] == 80000
    assert sold["net_proceeds_cents"] == 920000
    assert get_vehicle(vehicle["id"])["lifecycle_status"] == "DISPOSED"
    assert get_department(dep["id"])["billed_ytd_cents"] == -920000


# ─── cross_cutting_complexity_layers / work_order_on_disposed_vehicle_returns_vehicle_disposed ───

def test_work_order_on_disposed_vehicle_returns_vehicle_disposed(api):
    """PRD §3.3: "Scheduling a work order on a DISPOSED vehicle is rejected with
    ERR_VEHICLE_DISPOSED."

    Design: Corner/cross_cutting_complexity_layers/work_order_on_disposed_vehicle_returns_vehicle_disposed
    """
    vehicle = create_flagged_vehicle()
    disposal = create_bidding_disposal(vehicle["id"], reserve_price_cents=100000)
    validate_success(api.sell_disposal(
        disposal["id"], {"sale_price_cents": 200000, "buyer_name": "W"}, ADMIN), 200)
    assert get_vehicle(vehicle["id"])["lifecycle_status"] == "DISPOSED"
    bay = create_shop_bay(name="Bay-DIS")
    res = api.create_work_order(create_work_order_payload(
        vehicle["id"], bay["id"], scheduled_start="2026-06-10T09:00:00Z",
        scheduled_end="2026-06-10T11:00:00Z"), TECH)
    validate_error(res, "ERR_VEHICLE_DISPOSED")
