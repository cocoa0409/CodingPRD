"""Difficulty queue A — rules 3 (non_linear_state_machine), 4 (transitive_cascade), 5 (priority_pair_validation_conflict)."""

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_market_price_payload,
    create_route_payload,
    create_route_stop_payload,
    create_sample_screening_payload,
    create_pickup_ticket_payload,
    create_disposal_facility_payload,
    create_manifest_payload,
    create_active_customer_with_installed_tank,
    create_customer,
    create_driver,
    create_route,
    add_stop_to_route,
    publish_price,
    create_disposal_facility,
    setup_ready_to_pump_stop,
    setup_completed_pickup,
    setup_manifest_delivered,
)


# =========================================================================
# RULE 3 — non_linear_state_machine / manifest_amendment_cycle
# =========================================================================

def test_manifest_amendment_cycle_reenters_submitted(api):
    """PRD §3.7: "The amendment loop makes the manifest cyclic" and "moves the manifest to `AMENDED` — from which submission restarts the cycle."

    Design: Difficulty/non_linear_state_machine/manifest_amendment_cycle
    """
    ctx = setup_manifest_delivered(manifest_tracking_number="MAN-CYC-1", facility_epa_id="EPAID-CYC1")
    man_id = ctx["manifest"]["id"]
    # DELIVERED → AMENDMENT_PENDING
    m = get_success_data(api_client.request_amendment_manifest(man_id, TEST_USERS["route_planner_headers"]))
    assert m["status"] == "AMENDMENT_PENDING"
    # AMENDMENT_PENDING → AMENDED (recompute)
    m = get_success_data(api_client.approve_amendment_manifest(man_id, TEST_USERS["regulator_headers"]))
    assert m["status"] == "AMENDED"
    assert m["total_gallons_manifested"] == 100  # recomputed from COMPLETED stops
    # AMENDED → SUBMITTED (cycle)
    m = get_success_data(api_client.submit_manifest(man_id, TEST_USERS["route_planner_headers"]))
    assert m["status"] == "SUBMITTED"


def test_manifest_amendment_recomputes_total_on_approve(api):
    """PRD §3.7: "Regulator approval requires `AMENDMENT_PENDING` (otherwise `ERR_MANIFEST_NOT_PENDING_AMENDMENT`), recomputes `total_gallons_manifested` from the route's currently `COMPLETED` stops as a reconciliation".

    Design: Difficulty/non_linear_state_machine/manifest_amendment_cycle
    """
    ctx = setup_manifest_delivered(manifest_tracking_number="MAN-CYC-2", facility_epa_id="EPAID-CYC2")
    man_id = ctx["manifest"]["id"]
    assert ctx["manifest"]["total_gallons_manifested"] == 100
    api_client.request_amendment_manifest(man_id, TEST_USERS["route_planner_headers"])
    amended = get_success_data(api_client.approve_amendment_manifest(man_id, TEST_USERS["regulator_headers"]))
    assert amended["status"] == "AMENDED"
    # Recomputed total is still 100 — reflects the one COMPLETED stop
    assert amended["total_gallons_manifested"] == 100


# =========================================================================
# RULE 3 — non_linear_state_machine / tank_parallel_ownership_x_quarantine_dimensions
# =========================================================================

def test_halogen_quarantine_does_not_advance_ownership_status(api):
    """PRD §3.2: "Quarantine is a parallel hazard dimension orthogonal to the ownership lifecycle. A tank moves `CLEAR` → `QUARANTINED` automatically when a screening on that tank returns a halogen failure".

    Design: Difficulty/non_linear_state_machine/tank_parallel_ownership_x_quarantine_dimensions
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="PAR-Q",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    # Pre-state: ownership INSTALLED, quarantine CLEAR
    assert base["tank"]["ownership_status"] == "INSTALLED"
    # Halogen fail
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    tank_after = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert tank_after["quarantine_status"] == "QUARANTINED"
    assert tank_after["ownership_status"] == "INSTALLED"  # unchanged


def test_halogen_quarantine_does_not_change_ownership_for_customer_owned(api):
    """PRD §3.2: "Quarantine is a parallel hazard dimension orthogonal to the ownership lifecycle."

    Design: Difficulty/non_linear_state_machine/tank_parallel_ownership_x_quarantine_dimensions
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100, ownership="CUSTOMER_OWNED")
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="PAR-Q2",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(halogen_ppm=5000), TEST_USERS["lab_tech_headers"],
    ))
    tank_after = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert tank_after["quarantine_status"] == "QUARANTINED"
    assert tank_after["ownership_status"] == "INSTALLED"


# =========================================================================
# RULE 4 — transitive_cascade / halogen_screen_cascade_depth_3
# =========================================================================

def test_halogen_screen_cascade_stop_tank_customer(api):
    """PRD §3.4: "A `FAIL_HALOGEN` result moves the stop to `CANCELLED_HALOGEN`, quarantines the tank (`CLEAR` → `QUARANTINED`, which also cancels any other `SCHEDULED` or `EN_ROUTE` stop on the same tank), and increments the customer's `halogen_violation_count` by one".

    Design: Difficulty/transitive_cascade/halogen_screen_cascade_depth_3
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="C3",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    # Link 1: stop CANCELLED_HALOGEN
    stop_after = get_success_data(api_client.get_route_stop(stop["id"], drv))
    assert stop_after["status"] == "CANCELLED_HALOGEN"
    # Link 2: tank QUARANTINED
    tank_after = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert tank_after["quarantine_status"] == "QUARANTINED"
    # Link 3: customer halogen_violation_count incremented
    cust_after = get_success_data(api_client.get_customer(base["customer"]["id"], TEST_USERS["settlement_clerk_headers"]))
    assert cust_after["halogen_violation_count"] == 1


def test_halogen_screen_result_is_fail_halogen(api):
    """PRD §3.4: "The server computes the `result` — `PASS`, `FAIL_HALOGEN`, `FAIL_WATER`, or `FAIL_PH` — by comparing the measurements against the screening thresholds appropriate to the tank's `tank_kind`".

    Design: Difficulty/transitive_cascade/halogen_screen_cascade_depth_3
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="C3B",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    screening = get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    assert screening["result"] == "FAIL_HALOGEN"


# =========================================================================
# RULE 4 — transitive_cascade / spill_reportable_quantity_cascade_depth_2
# =========================================================================

def test_reportable_spill_contaminates_site_and_quarantines_all_tanks(api):
    """PRD §3.9: "such a reportable spill immediately drives its tank site to `CONTAMINATED`, which in turn quarantines every tank at the site (`CLEAR` → `QUARANTINED`)".

    Design: Difficulty/transitive_cascade/spill_reportable_quantity_cascade_depth_2
    """
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=500)
    # Second tank at same site
    tank2 = get_success_data(api_client.create_tank(
        {"tank_site_id": base["site"]["id"], "tank_kind": "ANTIFREEZE", "capacity_gallons": 300, "ownership": "CUSTOMER_OWNED"},
        TEST_USERS["tank_installer_headers"],
    ))
    tank2 = get_success_data(api_client.register_existing_tank(tank2["id"], TEST_USERS["tank_installer_headers"]))
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="SP-CAS2",
                         vehicle_capacity_gallons=500)
    drv = make_driver_headers(driver["id"])
    spill = get_success_data(api_client.create_spill_incident(
        {"route_id": route["id"], "tank_site_id": base["site"]["id"], "gallons_spilled": 30, "cause_code": "CUSTOMER_OVERFILL"},
        drv,
    ))
    assert spill["reportable_quantity_exceeded"] is True
    site_after = get_success_data(api_client.get_tank_site(base["site"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert site_after["status"] == "CONTAMINATED"
    t1 = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    t2 = get_success_data(api_client.get_tank(tank2["id"], TEST_USERS["ehs_officer_headers"]))
    assert t1["quarantine_status"] == "QUARANTINED"
    assert t2["quarantine_status"] == "QUARANTINED"


def test_reportable_spill_under_threshold_does_not_contaminate(api):
    """PRD §3.9: "The reportable-quantity threshold is 25 gallons: a spill of 25 gallons or more sets `reportable_quantity_exceeded` true".

    Design: Difficulty/transitive_cascade/spill_reportable_quantity_cascade_depth_2
    """
    base = create_active_customer_with_installed_tank(tank_kind="USED_OIL", capacity_gallons=500)
    driver = create_driver()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="SP-CAS3",
                         vehicle_capacity_gallons=500)
    drv = make_driver_headers(driver["id"])
    spill = get_success_data(api_client.create_spill_incident(
        {"route_id": route["id"], "tank_site_id": base["site"]["id"], "gallons_spilled": 10, "cause_code": "CUSTOMER_OVERFILL"},
        drv,
    ))
    assert spill["reportable_quantity_exceeded"] is False
    site_after = get_success_data(api_client.get_tank_site(base["site"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert site_after["status"] == "ACTIVE"
    t = get_success_data(api_client.get_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    assert t["quarantine_status"] == "CLEAR"


# =========================================================================
# RULE 5 — priority_pair_validation_conflict / state_vs_business_safety_on_arrive
# =========================================================================

def test_arrive_on_cancelled_stop_yields_state_error_not_safety(api):
    """PRD §2.6: "the first failure short-circuits the remainder" and state preconditions (priority 5) precede business rules (priority 7: "safety rules first (quarantine and site-contamination gates on arrival and screening...)" within business).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_arrive
    """
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="PPC1",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    # Drive tank to QUARANTINED via a separate route's halogen screen (cascade cancels stop S1)
    route_q = create_route(driver["id"], scheduled_date="2026-08-04", route_code="PPC1-Q",
                           vehicle_capacity_gallons=500)
    stop_q = add_stop_to_route(route_q["id"], base["site"]["id"], base["tank"]["id"], route_q["version"])
    route_q = get_success_data(api_client.dispatch_route(route_q["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop_q = get_success_data(api_client.arrive_route_stop(stop_q["id"], drv))
    stop_q = get_success_data(api_client.begin_screening_route_stop(stop_q["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop_q["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    # Now: original stop is CANCELLED_HALOGEN (cascade), route still PLANNED, tank QUARANTINED.
    # Attempting arrive → state check (stop not SCHEDULED) fires before safety.
    resp = api_client.arrive_route_stop(stop["id"], drv)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)


def test_arrive_state_error_precedes_quarantine_check(api):
    """PRD §2.6: "checks are evaluated in a fixed order, and the first failure short-circuits the remainder."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_arrive
    """
    # Stop is in CANCELLED_HALOGEN (post-cascade) AND tank is QUARANTINED; only state error fires.
    base = create_active_customer_with_installed_tank(intake_gallons=100)
    driver = create_driver()
    publish_price()
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="PPC1B",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    route_q = create_route(driver["id"], scheduled_date="2026-08-04", route_code="PPC1B-Q",
                           vehicle_capacity_gallons=500)
    stop_q = add_stop_to_route(route_q["id"], base["site"]["id"], base["tank"]["id"], route_q["version"])
    route_q = get_success_data(api_client.dispatch_route(route_q["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop_q = get_success_data(api_client.arrive_route_stop(stop_q["id"], drv))
    stop_q = get_success_data(api_client.begin_screening_route_stop(stop_q["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop_q["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    resp = api_client.arrive_route_stop(stop["id"], drv)
    data = validate_error(resp, ApiErrorId.ERR_STOP_NOT_SCHEDULED)
    assert resp.status_code == 409


# =========================================================================
# RULE 5 — priority_pair_validation_conflict / business_referential_vs_business_fiscal_on_settle
# =========================================================================

def test_halogen_flagged_manifest_rejected_by_facility_before_fiscal(api):
    """PRD §2.6: "When a manifest is submitted, the facility gates — facility active, daily capacity, and halogenated-stream acceptance — are evaluated before the temporal check" and PRD §3.7: "when `halogen_flag` is true, `HALOGENATED` appears in the facility's `accepted_streams` (otherwise `ERR_FACILITY_REJECTS_HALOGENATED`)".

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_settle
    """
    base = create_active_customer_with_installed_tank(
        credit_terms="NET30", route_eligibility_override=True, intake_gallons=200,
    )
    driver = create_driver()
    publish_price()
    facility = create_disposal_facility(epa_id="EPAID-PPC2", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=10000)
    # Drive tank QUARANTINED via halogen screen (no pickup — that stop is cascade-cancelled)
    route_q = create_route(driver["id"], scheduled_date="2026-08-04", route_code="PPC2-Q",
                           vehicle_capacity_gallons=500)
    stop_q = add_stop_to_route(route_q["id"], base["site"]["id"], base["tank"]["id"], route_q["version"])
    route_q = get_success_data(api_client.dispatch_route(route_q["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop_q = get_success_data(api_client.arrive_route_stop(stop_q["id"], drv))
    stop_q = get_success_data(api_client.begin_screening_route_stop(stop_q["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop_q["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.clear_quarantine_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    # Real pickup on previously-quarantined tank → halogen_flag=True on manifest
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="PPC2-R",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    manifest = get_success_data(api_client.create_manifest(
        route["id"],
        create_manifest_payload(facility["id"], manifest_tracking_number="MAN-PPC2"),
        TEST_USERS["route_planner_headers"],
    ))
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="PT-PPC2", metered_volume_gallons=100), drv,
    ))
    # Manifest should have halogen_flag=True
    manifest = get_success_data(api_client.get_manifest(manifest["id"], TEST_USERS["route_planner_headers"]))
    assert manifest["halogen_flag"] is True
    # Facility does NOT accept HALOGENATED
    resp = api_client.submit_manifest(manifest["id"], TEST_USERS["route_planner_headers"])
    validate_error(resp, ApiErrorId.ERR_FACILITY_REJECTS_HALOGENATED)


def test_halogen_flagged_manifest_facility_rejection_status(api):
    """PRD §3.7: "when `halogen_flag` is true, `HALOGENATED` appears in the facility's `accepted_streams` (otherwise `ERR_FACILITY_REJECTS_HALOGENATED`)".

    Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_settle
    """
    base = create_active_customer_with_installed_tank(
        credit_terms="NET30", route_eligibility_override=True, intake_gallons=200,
    )
    driver = create_driver()
    publish_price()
    facility = create_disposal_facility(epa_id="EPAID-PPC3", accepted_streams=["USED_OIL"],
                                        daily_capacity_gallons=10000)
    route_q = create_route(driver["id"], scheduled_date="2026-08-04", route_code="PPC3-Q",
                           vehicle_capacity_gallons=500)
    stop_q = add_stop_to_route(route_q["id"], base["site"]["id"], base["tank"]["id"], route_q["version"])
    route_q = get_success_data(api_client.dispatch_route(route_q["id"], TEST_USERS["route_planner_headers"]))
    drv = make_driver_headers(driver["id"])
    stop_q = get_success_data(api_client.arrive_route_stop(stop_q["id"], drv))
    stop_q = get_success_data(api_client.begin_screening_route_stop(stop_q["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop_q["id"], create_sample_screening_payload(halogen_ppm=9999), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.clear_quarantine_tank(base["tank"]["id"], TEST_USERS["ehs_officer_headers"]))
    route = create_route(driver["id"], scheduled_date="2026-08-05", route_code="PPC3-R",
                         vehicle_capacity_gallons=500)
    stop = add_stop_to_route(route["id"], base["site"]["id"], base["tank"]["id"], route["version"])
    manifest = get_success_data(api_client.create_manifest(
        route["id"],
        create_manifest_payload(facility["id"], manifest_tracking_number="MAN-PPC3"),
        TEST_USERS["route_planner_headers"],
    ))
    route = get_success_data(api_client.dispatch_route(route["id"], TEST_USERS["route_planner_headers"]))
    stop = get_success_data(api_client.arrive_route_stop(stop["id"], drv))
    stop = get_success_data(api_client.begin_screening_route_stop(stop["id"], drv))
    get_success_data(api_client.create_sample_screening(
        stop["id"], create_sample_screening_payload(), TEST_USERS["lab_tech_headers"],
    ))
    get_success_data(api_client.create_pickup_ticket(
        stop["id"], create_pickup_ticket_payload(client_request_id="PT-PPC3", metered_volume_gallons=100), drv,
    ))
    resp = api_client.submit_manifest(manifest["id"], TEST_USERS["route_planner_headers"])
    data = validate_error(resp, ApiErrorId.ERR_FACILITY_REJECTS_HALOGENATED)
    assert resp.status_code == 409
