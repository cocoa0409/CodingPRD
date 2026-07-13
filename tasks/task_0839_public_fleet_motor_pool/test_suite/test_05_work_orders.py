"""Work-order scheduling and start: bay availability, buffer conflicts, safety precedence."""
from test_helpers import (
    validate_success, validate_error,
    create_pool_vehicle, create_shop_bay, create_scheduled_work_order,
    get_vehicle, create_work_order_payload, create_accident_claim_payload,
    TEST_USERS,
)

TECH = TEST_USERS["shop_tech_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# ─── cross_entity_state_dependency / workorder_start_depends_on_bay_available ───

def test_start_workorder_closed_bay_returns_bay_closed(api):
    """PRD §3.3: "A ShopTech starts the order, which is permitted only when the target
    bay is AVAILABLE (otherwise ERR_BAY_CLOSED)".

    Design: Difficulty/cross_entity_state_dependency/workorder_start_depends_on_bay_available
    """
    vehicle = create_pool_vehicle(vin="VIN-7B")
    bay = create_shop_bay(name="Bay-7B")
    wo = create_scheduled_work_order(vehicle["id"], bay["id"])
    validate_success(api.update_shop_bay(bay["id"], {"status": "CLOSED"}, TECH), 200)
    validate_error(api.start_work_order(wo["id"], TECH), "ERR_BAY_CLOSED")


def test_start_workorder_available_bay_moves_vehicle_in_shop(api):
    """PRD §3.3: "starting drives SCHEDULED → IN_PROGRESS and moves the vehicle's
    operational_status to IN_SHOP."

    Design: Difficulty/cross_entity_state_dependency/workorder_start_depends_on_bay_available
    """
    vehicle = create_pool_vehicle(vin="VIN-7B-OK")
    bay = create_shop_bay(name="Bay-7B-OK")
    wo = create_scheduled_work_order(vehicle["id"], bay["id"])
    started = validate_success(api.start_work_order(wo["id"], TECH), 200)
    assert started["status"] == "IN_PROGRESS"
    assert get_vehicle(vehicle["id"])["operational_status"] == "IN_SHOP"


# ─── resource_temporal_overlap / bay_workorder_closed_interval_buffer_conflict ───

def test_bay_buffer_conflict_within_60_minutes(api):
    """PRD §3.3: "the new order conflicts if its start is earlier than an existing
    order's end plus 60 minutes while that existing order's start is earlier than the
    new order's end plus 60 minutes; windows that merely abut, or sit inside the
    60-minute buffer gap, still conflict and are rejected with ERR_BAY_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/bay_workorder_closed_interval_buffer_conflict
    """
    v1 = create_pool_vehicle(vin="VIN-8B-1")
    v2 = create_pool_vehicle(vin="VIN-8B-2")
    bay = create_shop_bay(name="Bay-8B")
    create_scheduled_work_order(v1["id"], bay["id"],
                                scheduled_start="2026-06-02T10:00:00Z",
                                scheduled_end="2026-06-02T12:00:00Z")
    res = api.create_work_order(create_work_order_payload(
        v2["id"], bay["id"], scheduled_start="2026-06-02T12:30:00Z",
        scheduled_end="2026-06-02T13:30:00Z"), TECH)
    validate_error(res, "ERR_BAY_TIME_CONFLICT")


def test_bay_separation_of_60_minutes_is_allowed(api):
    """PRD §3.3: "a new order must be separated from every non-terminal work order
    already on that same bay by at least 60 minutes (the bay buffer)."

    Design: Difficulty/resource_temporal_overlap/bay_workorder_closed_interval_buffer_conflict
    """
    v1 = create_pool_vehicle(vin="VIN-8B-1b")
    v2 = create_pool_vehicle(vin="VIN-8B-2b")
    bay = create_shop_bay(name="Bay-8Bb")
    create_scheduled_work_order(v1["id"], bay["id"],
                                scheduled_start="2026-06-02T10:00:00Z",
                                scheduled_end="2026-06-02T12:00:00Z")
    res = api.create_work_order(create_work_order_payload(
        v2["id"], bay["id"], scheduled_start="2026-06-02T13:00:00Z",
        scheduled_end="2026-06-02T14:00:00Z"), TECH)
    validate_success(res, 201)


# ─── priority_pair_validation_conflict / safety_beats_temporal_on_pm_workorder ───

def test_pm_on_open_accident_with_bay_conflict_reports_safety(api):
    """PRD §3.3: "a preventive-maintenance order (wo_type PM) may not be scheduled on a
    vehicle that has any open accident — that is, whose open_accident_count is greater
    than zero — because accident repair takes precedence; this is rejected with
    ERR_OPEN_ACCIDENT_BLOCKS_WO."
    PRD §2.8: "a lower-numbered failure always masks a higher-numbered one on the same
    request." (safety gates are tier 7; temporal-conflict gates are tier 8.)

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_pm_workorder
    """
    clean = create_pool_vehicle(vin="VIN-CLEAN-1")
    acc = create_pool_vehicle(vin="VIN-ACC-1")
    bay = create_shop_bay(name="Bay-SH")
    create_scheduled_work_order(clean["id"], bay["id"],
                                scheduled_start="2026-06-02T10:00:00Z",
                                scheduled_end="2026-06-02T12:00:00Z")
    validate_success(api.create_accident_claim(
        create_accident_claim_payload(acc["id"], at_fault=False,
                                      estimated_damage_cents=10000,
                                      third_party_liable_pct=0.5), FIN), 201)
    res = api.create_work_order(create_work_order_payload(
        acc["id"], bay["id"], wo_type="PM",
        scheduled_start="2026-06-02T11:00:00Z",
        scheduled_end="2026-06-02T13:00:00Z"), TECH)
    validate_error(res, "ERR_OPEN_ACCIDENT_BLOCKS_WO")


def test_pm_on_open_accident_vehicle_reports_safety_isolated(api):
    """PRD §3.3: "a preventive-maintenance order (wo_type PM) may not be scheduled on a
    vehicle that has any open accident — that is, whose open_accident_count is greater
    than zero — because accident repair takes precedence; this is rejected with
    ERR_OPEN_ACCIDENT_BLOCKS_WO."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_pm_workorder
    """
    acc = create_pool_vehicle(vin="VIN-ACC-2")
    bay = create_shop_bay(name="Bay-SH2")
    validate_success(api.create_accident_claim(
        create_accident_claim_payload(acc["id"], at_fault=False,
                                      estimated_damage_cents=10000,
                                      third_party_liable_pct=0.5), FIN), 201)
    res = api.create_work_order(create_work_order_payload(
        acc["id"], bay["id"], wo_type="PM",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T11:00:00Z"), TECH)
    validate_error(res, "ERR_OPEN_ACCIDENT_BLOCKS_WO")


# ─── state_machines / workorder_awaiting_parts_resume_cycle ───

def test_workorder_awaiting_parts_resume_cycle(api):
    """PRD §3.3: "The same start action resumes an order from AWAITING_PARTS back to
    IN_PROGRESS."
    PRD §3.3: "Putting an in-progress order on a parts hold drives IN_PROGRESS →
    AWAITING_PARTS, and cancelling is allowed only from SCHEDULED."

    Design: Corner/state_machines/workorder_awaiting_parts_resume_cycle
    """
    vehicle = create_pool_vehicle(vin="VIN-WOC-1")
    bay = create_shop_bay(name="Bay-WOC")
    wo = create_scheduled_work_order(vehicle["id"], bay["id"])
    validate_success(api.start_work_order(wo["id"], TECH), 200)
    validate_success(api.hold_parts_work_order(wo["id"], TECH), 200)
    resumed = validate_success(api.start_work_order(wo["id"], TECH), 200)
    assert resumed["status"] == "IN_PROGRESS"
