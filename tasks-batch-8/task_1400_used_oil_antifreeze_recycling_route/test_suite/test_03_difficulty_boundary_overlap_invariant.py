"""Difficulty queue A — rules 6 (boundary_precision), 7 (cross_entity_state_dependency), 8 (resource_temporal_overlap), 9 (compensating_invariant)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_route_payload,
    create_route_stop_payload,
    create_sample_screening_payload,
    create_pickup_ticket_payload,
    create_disposal_facility_payload,
    create_manifest_payload,
    create_settle_payload,
    create_adjust_payload,
    create_active_customer_with_installed_tank,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
    create_disposal_facility,
    setup_ready_to_pump_stop,
    setup_completed_pickup,
    setup_settled_ticket,
)


# =========================================================================
# RULE 6 — boundary_precision_check / density_zone_minimum_at_exact_threshold
# =========================================================================

def test_density_zone_minimum_at_threshold_no_fee(api):
    """PRD §3.4: "A volume exactly equal to the zone minimum counts as meeting it — no density fee is charged".

    Design: Difficulty/boundary_precision_check/density_zone_minimum_at_exact_threshold
    """
    ctx = setup_completed_pickup(
        density_zone="URBAN", price_cents_per_gal=10, metered_volume_gallons=50,
        intake_gallons=200, route_eligibility_override=False, route_code="BND-A",
    )
    ticket = ctx["ticket"]
    assert ticket["density_fee_cents"] == 0
    assert ticket["net_amount_cents"] == 500  # 50*10 - 0 - 0


def test_density_zone_minimum_one_below_threshold_triggers_fee(api):
    """PRD §3.4: "a volume one gallon below the minimum triggers the fee-or-skip logic" and PRD §3.5: "otherwise it is the shortfall — the zone minimum minus the metered volume — multiplied by the zone's per-gallon fee".

    Design: Difficulty/boundary_precision_check/density_zone_minimum_at_exact_threshold
    """
    ctx = setup_completed_pickup(
        density_zone="URBAN", price_cents_per_gal=10, metered_volume_gallons=49,
        intake_gallons=200, route_eligibility_override=False, route_code="BND-B",
    )
    ticket = ctx["ticket"]
    assert ticket["density_fee_cents"] == 20  # (50-49)*20
    assert ticket["net_amount_cents"] == 470  # 49*10 - 0 - 20


# =========================================================================
# RULE 6 — boundary_precision_check / vehicle_capacity_at_full_load
# =========================================================================

def test_route_capacity_at_equality_marks_at_capacity(api):
    """PRD §2.9: "`AT_CAPACITY` when `loaded_gallons` is greater than or equal to `vehicle_capacity_gallons` (equality counts as full)".

    Design: Difficulty/boundary_precision_check/vehicle_capacity_at_full_load
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=300,
    )
    driver = create_driver()
    publish_price(price_cents_per_gal=10)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="CAP",
                         vehicle_capacity_gallons=100)
    stop1 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="08:00", scheduled_window_end="09:00", sequence=1,
                              estimated_volume_gallons=50)
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop2 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="10:00", scheduled_window_end="11:00", sequence=2,
                              estimated_volume_gallons=50)
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    # Stop 1: 50 gal
    stop1 = get_success_data(api_client.arrive_route_stop(stop1["id"], drv))
    stop1 = get_success_data(api_client.begin_screening_route_stop(stop1["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop1["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop1["id"], create_pickup_ticket_payload(client_request_id="CAP-1", metered_volume_gallons=50), drv,
    ))
    route_mid = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert route_mid["posture"] == "OPEN"
    assert route_mid["loaded_gallons"] == 50
    # Stop 2: another 50 → loaded == capacity
    stop2 = get_success_data(api_client.arrive_route_stop(stop2["id"], drv))
    stop2 = get_success_data(api_client.begin_screening_route_stop(stop2["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop2["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop2["id"], create_pickup_ticket_payload(client_request_id="CAP-2", metered_volume_gallons=50), drv,
    ))
    route_final = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert route_final["loaded_gallons"] == 100
    assert route_final["posture"] == "AT_CAPACITY"


def test_route_capacity_exceeded_rejected_422(api):
    """PRD §3.4: "volume that would push the route's `loaded_gallons` past `vehicle_capacity_gallons` yields `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422)".

    Design: Difficulty/boundary_precision_check/vehicle_capacity_at_full_load
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=300,
    )
    driver = create_driver()
    publish_price(price_cents_per_gal=10)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="CAP2",
                         vehicle_capacity_gallons=100)
    stop1 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="08:00", scheduled_window_end="09:00", sequence=1,
                              estimated_volume_gallons=50)
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop2 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="10:00", scheduled_window_end="11:00", sequence=2,
                              estimated_volume_gallons=50)
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop3 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="12:00", scheduled_window_end="13:00", sequence=3,
                              estimated_volume_gallons=1)
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    for s, m, cid in [(stop1, 50, "CAP2-1"), (stop2, 50, "CAP2-2")]:
        s = get_success_data(api_client.arrive_route_stop(s["id"], drv))
        s = get_success_data(api_client.begin_screening_route_stop(s["id"], drv))
        get_success_data(api_client.create_sample_screening(
            s["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
        ))
        get_success_data(api_client.create_pickup_ticket(
            s["id"], create_pickup_ticket_payload(client_request_id=cid, metered_volume_gallons=m), drv,
        ))
    # Stop 3: 1 gal would push 100 → 101 > 100
    stop3 = get_success_data(api_client.arrive_route_stop(stop3["id"], drv))
    stop3 = get_success_data(api_client.begin_screening_route_stop(stop3["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop3["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    resp = api_client.create_pickup_ticket(
        stop3["id"],
        create_pickup_ticket_payload(client_request_id="CAP2-3", metered_volume_gallons=1),
        drv,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)


# =========================================================================
# RULE 7 — cross_entity_state_dependency / manifest_submit_depends_on_facility_state
# =========================================================================

def test_manifest_submit_blocked_when_facility_capacity_full(api):
    """PRD §3.7: "the facility's `scheduled_gallons_today` plus this manifest's total stays within `daily_capacity_gallons` (otherwise `ERR_FACILITY_CAPACITY_EXCEEDED`)".

    Design: Difficulty/cross_entity_state_dependency/manifest_submit_depends_on_facility_state
    """
    facility = create_disposal_facility(epa_id="EPAID-CAPF", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=100)
    ctx1 = setup_completed_pickup(
        price_cents_per_gal=50, metered_volume_gallons=100, route_eligibility_override=True,
        route_code="X1", manifest_facility_id=facility["id"],
    )
    # PRD §3.7 counts manifests "whose route's scheduled_date equals the server's
    # current date" — advance the logical clock (§2.10) to the route's day.
    get_success_data(api_client.set_current_utc(
        {"to_iso8601": "2026-08-05T00:00:00Z"}, TEST_USERS["route_planner_headers"],
    ))
    get_success_data(api_client.submit_manifest(ctx1["manifest"]["id"], TEST_USERS["route_planner_headers"]))
    fac_now = get_success_data(api_client.get_disposal_facility(facility["id"], TEST_USERS["regulator_headers"]))
    assert fac_now["scheduled_gallons_today"] == 100
    # Second manifest for another 50 gal — would exceed
    ctx2 = setup_completed_pickup(
        price_cents_per_gal=50, metered_volume_gallons=50, route_eligibility_override=True,
        route_code="X2", manifest_facility_id=facility["id"], intake_gallons=200,
        legal_name="SecondCust",
    )
    resp = api_client.submit_manifest(ctx2["manifest"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)


def test_manifest_submit_capacity_reflects_aggregate_state(api):
    """PRD §3.7: "the facility's `scheduled_gallons_today` is the sum of `total_gallons_manifested` across all manifests in `SUBMITTED`, `IN_TRANSIT`, or `AMENDMENT_PENDING` whose route's `scheduled_date` equals the server's current date".

    Design: Difficulty/cross_entity_state_dependency/manifest_submit_depends_on_facility_state
    """
    facility = create_disposal_facility(epa_id="EPAID-AGG", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=10000)
    ctx = setup_completed_pickup(
        price_cents_per_gal=50, metered_volume_gallons=100, route_eligibility_override=True,
        route_code="AGG1", manifest_facility_id=facility["id"],
    )
    # PRD §3.7 counts manifests "whose route's scheduled_date equals the server's
    # current date" — advance the logical clock (§2.10) to the route's day.
    get_success_data(api_client.set_current_utc(
        {"to_iso8601": "2026-08-05T00:00:00Z"}, TEST_USERS["route_planner_headers"],
    ))
    get_success_data(api_client.submit_manifest(ctx["manifest"]["id"], TEST_USERS["route_planner_headers"]))
    fac_now = get_success_data(api_client.get_disposal_facility(facility["id"], TEST_USERS["regulator_headers"]))
    assert fac_now["scheduled_gallons_today"] == 100


# =========================================================================
# RULE 7 — cross_entity_state_dependency / route_stop_arrive_depends_on_tank_quarantine_state
# =========================================================================

def test_arrive_succeeds_when_tank_clear_even_with_other_tank_quarantined(api):
    """PRD §3.4: "Arrival requires the stop to be `SCHEDULED`..., the tank's `quarantine_status` to be `CLEAR` (otherwise `ERR_TANK_QUARANTINED`)".

    Design: Difficulty/cross_entity_state_dependency/route_stop_arrive_depends_on_tank_quarantine_state
    """
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=500)
    # Second tank at same site — T2
    tank2 = get_success_data(api_client.create_tank(
        {"tank_site_id": base["site"]["id"], "tank_kind": "USED_OIL", "capacity_gallons": 500, "ownership": "CUSTOMER_OWNED"},
        TEST_USERS["tank_installer_headers"],
    ))
    tank2 = get_success_data(api_client.register_existing_tank(tank2["id"], TEST_USERS["tank_installer_headers"]))
    # Intake both
    api_client.record_intake(base["tank"]["id"], {"gallons": 100}, TEST_USERS["route_planner_headers"])
    api_client.record_intake(tank2["id"], {"gallons": 100}, TEST_USERS["route_planner_headers"])
    driver = create_driver()
    publish_price()
    # Quarantine T1 via halogen screen
    route_a = create_route(driver["id"], scheduled_date="2026-08-05", route_code="X-A", vehicle_capacity_gallons=500)
    stop_a = add_stop_to_route(route_a["id"], base["site"]["id"], base["tank"]["id"], route_a["version"])
    route_a = get_success_data(api_client.dispatch_route(route_a["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop_a = get_success_data(api_client.arrive_route_stop(stop_a["id"], drv))
    stop_a = get_success_data(api_client.begin_screening_route_stop(stop_a["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop_a["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    t1_now = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert t1_now["quarantine_status"] == "QUARANTINED"
    t2_now = get_success_data(api_client.get_tank(tank2["id"], TEST_USERS["ehs_officer_headers"]))
    assert t2_now["quarantine_status"] == "CLEAR"
    # Arrive on T2 stop succeeds
    route_b = create_route(driver["id"], scheduled_date="2026-08-05", route_code="X-B", vehicle_capacity_gallons=500)
    stop_b = add_stop_to_route(route_b["id"], base["site"]["id"], tank2["id"], route_b["version"])
    route_b = get_success_data(api_client.dispatch_route(route_b["id"], TEST_USERS["route_planner_headers"]))
    stop_b = get_success_data(api_client.arrive_route_stop(stop_b["id"], drv))
    assert stop_b["status"] == "EN_ROUTE"


def test_arrive_blocked_when_tank_quarantined_yields_state_error_after_cascade(api):
    """PRD §3.4: "the tank's `quarantine_status` to be `CLEAR` (otherwise `ERR_TANK_QUARANTINED`)".

    Design: Difficulty/cross_entity_state_dependency/route_stop_arrive_depends_on_tank_quarantine_state
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="X-C", vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    # Quarantine the tank via a different route — cascades stop to CANCELLED_HALOGEN
    route_q = create_route(driver["id"], scheduled_date="2026-08-04", route_code="X-C-Q", vehicle_capacity_gallons=500)
    stop_q = add_stop_to_route(route_q["id"], base["site"]["id"], base["tank"]["id"], route_q["version"])
    route_q = get_success_data(api_client.dispatch_route(route_q["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop_q = get_success_data(api_client.arrive_route_stop(stop_q["id"], drv))
    stop_q = get_success_data(api_client.begin_screening_route_stop(stop_q["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop_q["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    # Stop is now CANCELLED_HALOGEN — arrive attempt fails on state check
    resp = api_client.arrive_route_stop(stop["id"], drv)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)


# =========================================================================
# RULE 8 — resource_temporal_overlap / route_capacity_aggregate_overlap
# =========================================================================

def test_route_capacity_aggregate_accumulates_across_stops(api):
    """PRD §3.4: "volume that would push the route's `loaded_gallons` past `vehicle_capacity_gallons` yields `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/route_capacity_aggregate_overlap
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=300,
    )
    driver = create_driver()
    publish_price(price_cents_per_gal=10)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="OV",
                         vehicle_capacity_gallons=120)
    stop1 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="08:00", scheduled_window_end="09:00", sequence=1,
                              estimated_volume_gallons=80)
    route = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop2 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"],
                              scheduled_window_start="10:00", scheduled_window_end="11:00", sequence=2,
                              estimated_volume_gallons=50)
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    # Stop 1: 80 gal (succeeds, loaded = 80)
    stop1 = get_success_data(api_client.arrive_route_stop(stop1["id"], drv))
    stop1 = get_success_data(api_client.begin_screening_route_stop(stop1["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop1["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop1["id"], create_pickup_ticket_payload(client_request_id="OV-1", metered_volume_gallons=80), drv,
    ))
    route_now = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert route_now["loaded_gallons"] == 80
    # Stop 2: 50 gal would push to 130 > 120
    stop2 = get_success_data(api_client.arrive_route_stop(stop2["id"], drv))
    stop2 = get_success_data(api_client.begin_screening_route_stop(stop2["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop2["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    resp = api_client.create_pickup_ticket(
        stop2["id"],
        create_pickup_ticket_payload(client_request_id="OV-2", metered_volume_gallons=50),
        drv,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)


def test_route_capacity_first_pickup_under_cap_succeeds(api):
    """PRD §3.4: "On success the stop becomes `COMPLETED`, the tank's `current_volume_gallons` decreases by the metered volume, the route's `loaded_gallons` increases by the same amount".

    Design: Difficulty/resource_temporal_overlap/route_capacity_aggregate_overlap
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=300,
    )
    driver = create_driver()
    publish_price(price_cents_per_gal=10)
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="OV-OK",
                         vehicle_capacity_gallons=120)
    stop1 = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop1 = get_success_data(api_client.arrive_route_stop(stop1["id"], drv))
    stop1 = get_success_data(api_client.begin_screening_route_stop(stop1["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop1["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    ticket = get_success_data(api_client.create_pickup_ticket(
        stop1["id"], create_pickup_ticket_payload(client_request_id="OV-OK-1", metered_volume_gallons=80), drv,
    ))
    assert ticket["metered_volume_gallons"] == 80
    route_now = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert route_now["loaded_gallons"] == 80


# =========================================================================
# RULE 8 — resource_temporal_overlap / facility_daily_capacity_window
# =========================================================================

def test_facility_daily_window_resets_by_scheduled_date(api):
    """PRD §3.7: "The facility's `scheduled_gallons_today` is the sum of `total_gallons_manifested` across all manifests in `SUBMITTED`, `IN_TRANSIT`, or `AMENDMENT_PENDING` whose route's `scheduled_date` equals the server's current date".

    Design: Difficulty/resource_temporal_overlap/facility_daily_capacity_window
    """
    # Default clock is 2026-08-01; route scheduled for 2026-08-05 is "future" so submit works
    # The capacity window test here uses two different scheduled_dates so they occupy different windows.
    facility = create_disposal_facility(epa_id="EPAID-OVF", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=100)
    # Manifest 1: route on 2026-08-05 with 100 gal — fills the 2026-08-05 window
    ctx1 = setup_completed_pickup(
        price_cents_per_gal=10, metered_volume_gallons=100, route_eligibility_override=True,
        route_code="OVF-1", scheduled_date="2026-08-05", manifest_facility_id=facility["id"],
    )
    # PRD §3.7 aggregates per "the server's current date" — move the clock (§2.10)
    # onto each route's scheduled_date so its window is the active one.
    get_success_data(api_client.set_current_utc(
        {"to_iso8601": "2026-08-05T00:00:00Z"}, TEST_USERS["route_planner_headers"],
    ))
    m1 = get_success_data(api_client.submit_manifest(ctx1["manifest"]["id"], TEST_USERS["route_planner_headers"]))
    assert m1["status"] == "SUBMITTED"
    # Manifest 2: route on 2026-08-06 with 100 gal — different day window, succeeds
    ctx2 = setup_completed_pickup(
        price_cents_per_gal=10, metered_volume_gallons=100, route_eligibility_override=True,
        route_code="OVF-2", scheduled_date="2026-08-06", manifest_facility_id=facility["id"],
        legal_name="OvfCust2",
    )
    get_success_data(api_client.set_current_utc(
        {"to_iso8601": "2026-08-06T00:00:00Z"}, TEST_USERS["route_planner_headers"],
    ))
    m2 = get_success_data(api_client.submit_manifest(ctx2["manifest"]["id"], TEST_USERS["route_planner_headers"]))
    assert m2["status"] == "SUBMITTED"


def test_facility_daily_window_same_day_second_submit_blocked(api):
    """PRD §3.7: "the facility's `scheduled_gallons_today` plus this manifest's total stays within `daily_capacity_gallons` (otherwise `ERR_FACILITY_CAPACITY_EXCEEDED`)".

    Design: Difficulty/resource_temporal_overlap/facility_daily_capacity_window
    """
    facility = create_disposal_facility(epa_id="EPAID-OVF2", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=100)
    ctx1 = setup_completed_pickup(
        price_cents_per_gal=10, metered_volume_gallons=100, route_eligibility_override=True,
        route_code="OVF2-A", scheduled_date="2026-08-05", manifest_facility_id=facility["id"],
    )
    # PRD §3.7 aggregates per "the server's current date" — move the clock (§2.10)
    # onto the shared scheduled_date so both manifests land in the active window.
    get_success_data(api_client.set_current_utc(
        {"to_iso8601": "2026-08-05T00:00:00Z"}, TEST_USERS["route_planner_headers"],
    ))
    get_success_data(api_client.submit_manifest(ctx1["manifest"]["id"], TEST_USERS["route_planner_headers"]))
    ctx2 = setup_completed_pickup(
        price_cents_per_gal=10, metered_volume_gallons=100, route_eligibility_override=True,
        route_code="OVF2-B", scheduled_date="2026-08-05", manifest_facility_id=facility["id"],
        legal_name="OvfCust3",
    )
    resp = api_client.submit_manifest(ctx2["manifest"]["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)


# =========================================================================
# RULE 9 — compensating_invariant / tank_volume_conservation_across_pickup
# =========================================================================

def test_gallons_conserved_across_pickup_tank_route_manifest(api):
    """PRD §3.4: "On success the stop becomes `COMPLETED`, the tank's `current_volume_gallons` decreases by the metered volume, the route's `loaded_gallons` increases by the same amount... and — if a manifest already exists for the route — its `total_gallons_manifested` increases by the metered volume."

    Design: Difficulty/compensating_invariant/tank_volume_conservation_across_pickup
    """
    facility = create_disposal_facility(epa_id="EPAID-INV1", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=10000)
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=200,
    )
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="INV",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    manifest = get_success_data(api_client.create_manifest(
        route["id"], create_manifest_payload(facility["id"], manifest_tracking_number="INV-M"),
        TEST_USERS["route_planner_headers"],
    ))
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    # Pre-check: tank 200, route 0, manifest 0
    tank_pre = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert tank_pre["current_volume_gallons"] == 200
    get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="INV-PT", metered_volume_gallons=80), drv,
    ))
    tank_post = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    route_post = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    manifest_post = get_success_data(api_client.get_manifest(manifest["id"], TEST_USERS["route_planner_headers"]))
    assert tank_post["current_volume_gallons"] == 120
    assert route_post["loaded_gallons"] == 80
    assert manifest_post["total_gallons_manifested"] == 80
    assert tank_post["current_volume_gallons"] + route_post["loaded_gallons"] == 200


def test_gallons_conserved_tank_plus_route_equals_intake(api):
    """PRD §3.2: "a driver or planner records each such fill as an intake of `gallons`, which is added to `current_volume_gallons`" and PRD §3.4: "the tank's `current_volume_gallons` decreases by the metered volume, the route's `loaded_gallons` increases by the same amount".

    Design: Difficulty/compensating_invariant/tank_volume_conservation_across_pickup
    """
    base = create_active_customer_with_installed_tank(
        route_eligibility_override=True, intake_gallons=150,
    )
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="INV2",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="INV2-PT", metered_volume_gallons=100), drv,
    ))
    tank_post = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    route_post = get_success_data(api_client.get_route(route["id"], TEST_USERS["route_planner_headers"]))
    assert tank_post["current_volume_gallons"] + route_post["loaded_gallons"] == 150


# =========================================================================
# RULE 9 — compensating_invariant / customer_balance_conservation_across_adjust
# =========================================================================

def test_customer_balance_matches_final_net_after_settle_dispute_adjust(api):
    """PRD §3.6: "the customer is posted only the delta between the new and the old net when the ticket had previously settled".

    Design: Difficulty/compensating_invariant/customer_balance_conservation_across_adjust
    """
    ctx = setup_settled_ticket(
        credit_terms="PREPAY", price_cents_per_gal=50, metered_volume_gallons=100,
        intake_gallons=200, route_eligibility_override=True, route_code="INV2S",
    )
    cust = ctx["customer"]
    assert cust["prepaid_balance_cents"] == 5000  # settle posted +5000
    # Dispute + adjust to 80
    api_client.dispute_pickup_ticket(ctx["ticket"]["id"], TEST_USERS["settlement_clerk_headers"])
    api_client.adjust_pickup_ticket(
        ctx["ticket"]["id"],
        create_adjust_payload(corrected_metered_volume_gallons=80),
        TEST_USERS["settlement_clerk_headers"],
    )
    cust_after = get_success_data(api_client.get_customer(cust["id"], TEST_USERS["settlement_clerk_headers"]))
    ticket_after = get_success_data(api_client.get_pickup_ticket(ctx["ticket"]["id"], TEST_USERS["settlement_clerk_headers"]))
    assert ticket_after["net_amount_cents"] == 4000
    assert cust_after["prepaid_balance_cents"] == 4000  # delta -1000 posted
    assert cust_after["prepaid_balance_cents"] == ticket_after["net_amount_cents"]


def test_customer_balance_no_orphan_cents_across_adjust(api):
    """PRD §3.6: "the customer is posted only the delta between the new and the old net when the ticket had previously settled, or the full new net when it never settled."

    Design: Difficulty/compensating_invariant/customer_balance_conservation_across_adjust
    """
    ctx = setup_settled_ticket(
        credit_terms="PREPAY", price_cents_per_gal=50, metered_volume_gallons=100,
        intake_gallons=200, route_eligibility_override=True, route_code="INV2T",
    )
    api_client.dispute_pickup_ticket(ctx["ticket"]["id"], TEST_USERS["settlement_clerk_headers"])
    api_client.adjust_pickup_ticket(
        ctx["ticket"]["id"],
        create_adjust_payload(corrected_metered_volume_gallons=60),
        TEST_USERS["settlement_clerk_headers"],
    )
    cust_after = get_success_data(api_client.get_customer(ctx["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    ticket_after = get_success_data(api_client.get_pickup_ticket(ctx["ticket"]["id"], TEST_USERS["settlement_clerk_headers"]))
    # Final net = 50 * 60 = 3000; delta from settled = -2000
    assert ticket_after["net_amount_cents"] == 3000
    assert cust_after["prepaid_balance_cents"] == 3000
