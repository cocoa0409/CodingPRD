"""Every write answers with its own consequences already worked out, and the very next
read agrees with the answer."""

from test_helpers import (
    LANDLORD_HEADERS,
    assert_capacity_pool_identity,
    assert_ledger_identity,
    assert_money,
    assert_phase,
    assert_reservation,
    assert_utilization_report,
    create_phase,
    create_reservation,
    decide_hazmat_permit,
    file_hazmat_permit,
    get_building,
    get_lease,
    get_utilization,
    progress_phase,
    schedule_phase,
    setup_permitted_project,
    utc,
    validate_paginated,
)

NAMEPLATE = {
    "name": "Kendall Labs 400",
    "address_city": "Cambridge",
    "occupancy_status": "PARTIALLY_OCCUPIED",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}
PLATE = {
    "floor_to_floor_ft": 14.0,
    "live_load_psf": 95,
    "vibration_class": "VC_C",
    "sprinklered": True,
}
DEMAND = {
    "assessment_basis": "SCREENING",
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}
QC_LEASE = {
    "term_months": 120,
    "base_rent_psf": 95.00,
    "delivery_deadline": "2026-12-31T00:00:00Z",
}
QC_PROJECT = {
    "design_exhaust_cfm": 12000,
    "design_power_kw": 180,
    "scope_summary": "QC lab fit-out, floor 2",
}

PACKAGE_WINDOW = (utc(2026, 9, 1), utc(2026, 9, 5))


def test_the_read_that_follows_each_write_needs_no_second_attempt(api):
    """Three writes, and after each one the first read already tells the truth.

    Reserving capacity, approving a quantity of flammables and closing out a
    package each change something derived that lives somewhere other than the row
    written -- the asset's pools, the plate's report, the lease's ledger -- and
    every one of those figures is correct on the first read taken straight
    afterwards, with no retry and no settling time.

    Design: Corner/consistency_model/every_write_response_already_carries_its_recomputed_derived_state
    """
    bundle = setup_permitted_project(
        api,
        allowance_psf=70.00,
        research_type="ANALYTICAL_QC",
        premises_floor_number=2,
        floor_numbers=(2,),
        rentable_sf=2000,
        lease_overrides=dict(QC_LEASE),
        building_overrides=dict(NAMEPLATE),
        floor_overrides={2: dict(PLATE)},
        assessment_overrides=dict(DEMAND),
        project_overrides=dict(QC_PROJECT),
    )
    project_id = bundle["project"]["id"]
    building_id = bundle["building"]["id"]
    floor_id = bundle["premises_floor"]["id"]
    lease_id = bundle["lease"]["id"]
    permit = file_hazmat_permit(
        api, project_id, floor_id, "FLAMMABLE_IB", "CLOSED_SYSTEM_USE", 100.00, 1,
        bundle["tenant_headers"],
    )
    package = create_phase(
        api, project_id, 1, "SHELL", "QUIET", 100000.00, restoration_cost_usd=90000.00
    )
    schedule_phase(api, package["id"], *PACKAGE_WINDOW)
    progress_phase(api, package["id"], "IN_PROGRESS")
    asset = get_building(api, building_id)

    reservation = create_reservation(api, project_id, asset["version"], 12000, 180)
    pools = get_building(api, building_id)

    approved = decide_hazmat_permit(api, permit["id"], "APPROVE")
    report = get_utilization(api, floor_id, "FLAMMABLE_IB", 1)

    completed = progress_phase(api, package["id"], "COMPLETE")
    ledger = get_lease(api, lease_id)
    rows, meta = validate_paginated(
        api.list_phases(LANDLORD_HEADERS, {"project_id": project_id})
    )

    assert_reservation(reservation)
    assert reservation["status"] == "RESERVED"
    assert_money(pools["exhaust_reserved_cfm"], 12000.00, "exhaust_reserved_cfm")
    assert_money(pools["exhaust_available_cfm"], 68000.00, "exhaust_available_cfm")
    assert_money(pools["power_reserved_kw"], 180.00, "power_reserved_kw")
    assert_money(pools["power_available_kw"], 620.00, "power_available_kw")
    assert_capacity_pool_identity(pools)

    assert approved["status"] == "APPROVED"
    assert_utilization_report(report, floor_id, "FLAMMABLE_IB")
    assert_money(report["per_control_area_basis_gal"], 100.00, "per-area basis")
    assert_money(report["per_control_area_utilization_pct"], 55.56, "per-area pct")

    assert_phase(completed)
    assert completed["status"] == "COMPLETE"
    assert_money(completed["ti_eligible_usd"], 60000.00, "ti_eligible_usd")
    assert_money(completed["ti_committed_usd"], 60000.00, "ti_committed_usd")
    assert_money(ledger["ti_committed_usd"], 60000.00, "ti_committed_usd")
    assert_money(ledger["ti_uncommitted_usd"], 140000.00, "ti_uncommitted_usd")
    assert_money(ledger["ti_authorized_usd"], 200000.00, "ti_authorized_usd")
    assert_ledger_identity(ledger)
    assert meta["total_count"] == 1
    assert_money(rows[0]["ti_committed_usd"], 60000.00, "listed ti_committed_usd")
