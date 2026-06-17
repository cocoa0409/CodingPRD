"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before every test).
Setup calls use get_success_data() so a setup failure produces a clear error.

Identity threading: after creating an entity_backed actor (Technician / Customer),
ownership-gated calls use make_<role>_headers(entity_id), never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_technician_headers,
    make_customer_headers,
    make_backflow_tester_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitive creators
# ---------------------------------------------------------------------------
def create_customer(company_name="Test Co", contact_email="t@x.com", billing_zip="94016"):
    return get_success_data(api.create_customer(
        {"company_name": company_name, "contact_email": contact_email, "billing_zip": billing_zip},
        DISPATCHER,
    ))


def create_technician(full_name="Test Tech", shift_start_sec=28800, shift_end_sec=64800,
                      backflow_certified=None):
    payload = {"full_name": full_name, "shift_start_sec": shift_start_sec, "shift_end_sec": shift_end_sec}
    if backflow_certified is not None:
        payload["backflow_certified"] = backflow_certified
    return get_success_data(api.create_technician(payload, DISPATCHER))


def create_property(customer_id, site_address="1 Test St", lat=37.7, lng=-122.4):
    return get_success_data(api.create_property(
        {"customer_id": customer_id, "site_address": site_address, "lat": lat, "lng": lng},
        DISPATCHER,
    ))


def create_system(property_id, controller_model="Hunter", static_psi=60, has_backflow_device=None):
    payload = {"property_id": property_id, "controller_model": controller_model, "static_psi": static_psi}
    if has_backflow_device is not None:
        payload["has_backflow_device"] = has_backflow_device
    return get_success_data(api.create_system(payload, DISPATCHER))


def create_zone(system_id, zone_number, plant_type="TURF", head_count=8, gpm_per_head=18):
    return get_success_data(api.create_zone(
        {"system_id": system_id, "zone_number": zone_number, "plant_type": plant_type,
         "head_count": head_count, "gpm_per_head": gpm_per_head},
        DISPATCHER,
    ))


def create_work_order(system_id, job_type="HEAD_REPAIR", estimated_minutes=30, estimated_cost_cents=4000):
    return get_success_data(api.create_work_order(
        {"system_id": system_id, "job_type": job_type,
         "estimated_minutes": estimated_minutes, "estimated_cost_cents": estimated_cost_cents},
        DISPATCHER,
    ))


def create_route(technician_id, route_date="2026-05-01"):
    return get_success_data(api.create_route(
        {"technician_id": technician_id, "route_date": route_date}, DISPATCHER,
    ))


def create_route_stop(route_id, work_order_id, expected_route_version,
                      arrival_start_sec=28800, window_minutes=60):
    """Schedule a stop, then return the UPDATED ROUTE (not the RouteStop).

    PRD §4 / SCAFFOLD: POST /route-stops returns the created RouteStop object,
    which carries the stop's own id/version and stop_state — it does NOT carry
    the route's version, stops_used, or minutes_committed. Every fixture caller
    here needs the route's post-add picture: the threaded expected_route_version
    for the next stop (PRD §2.8), and the recomputed stops_used / minutes_committed
    (PRD §3.6). So this helper performs the follow-up GET /routes/{id} the PRD
    guarantees reflects the recompute, and returns that route. Tests that need the
    RouteStop object (stop_state) call api.create_route_stop directly.
    """
    get_success_data(api.create_route_stop(
        {"route_id": route_id, "work_order_id": work_order_id,
         "arrival_start_sec": arrival_start_sec, "window_minutes": window_minutes,
         "expected_route_version": expected_route_version},
        DISPATCHER,
    ))
    return get_success_data(api.get_route(route_id, DISPATCHER))


# ---------------------------------------------------------------------------
# Tier 2: common hierarchies
# ---------------------------------------------------------------------------
def setup_customer_property(company_name="CP Co"):
    """Returns (customer, property)."""
    cust = create_customer(company_name=company_name)
    prop = create_property(cust["id"])
    return cust, prop


def setup_customer_property_system(static_psi=60, has_backflow_device=None, company_name="CPS Co"):
    """Returns (customer, property, system)."""
    cust = create_customer(company_name=company_name)
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=static_psi, has_backflow_device=has_backflow_device)
    return cust, prop, sys


# ---------------------------------------------------------------------------
# Tier 3: work-order lifecycle shortcuts
# ---------------------------------------------------------------------------
def schedule_work_order(system_id, technician_id, job_type="LEAK_REPAIR",
                        estimated_minutes=30, estimated_cost_cents=4000,
                        route_date="2026-05-01", arrival_start_sec=28800, window_minutes=60):
    """Create a work order + route + route-stop so the WO becomes SCHEDULED.
    Returns (work_order_id, route_id, route_after_stop)."""
    wo = create_work_order(system_id, job_type=job_type,
                           estimated_minutes=estimated_minutes, estimated_cost_cents=estimated_cost_cents)
    route = create_route(technician_id, route_date=route_date)
    route_after = create_route_stop(route["id"], wo["id"], route["version"],
                                    arrival_start_sec=arrival_start_sec, window_minutes=window_minutes)
    return wo["id"], route["id"], route_after


def drive_work_order_to_in_progress(system_id, technician_id, job_type="LEAK_REPAIR",
                                    estimated_minutes=30, estimated_cost_cents=4000,
                                    route_date="2026-05-01"):
    """Schedule a WO, then depart + arrive as the assigned technician so that
    dispatch_status=ON_SITE and completion_status=IN_PROGRESS. Returns work_order_id."""
    wo_id, _route_id, _ = schedule_work_order(
        system_id, technician_id, job_type=job_type,
        estimated_minutes=estimated_minutes, estimated_cost_cents=estimated_cost_cents,
        route_date=route_date,
    )
    tech_headers = make_technician_headers(technician_id)
    get_success_data(api.depart_work_order(wo_id, tech_headers))
    get_success_data(api.arrive_work_order(wo_id, tech_headers))
    return wo_id


def complete_work_order_full(system_id, technician_id, job_type, actual_labor_cents,
                             actual_parts_cents, estimated_minutes=30, estimated_cost_cents=4000,
                             route_date="2026-05-01"):
    """Drive a fresh WO of job_type all the way to COMPLETED with the given actuals.
    Returns the completed work order data."""
    wo_id = drive_work_order_to_in_progress(
        system_id, technician_id, job_type=job_type,
        estimated_minutes=estimated_minutes, estimated_cost_cents=estimated_cost_cents,
        route_date=route_date,
    )
    tech_headers = make_technician_headers(technician_id)
    return get_success_data(api.complete_work_order(
        wo_id,
        {"actual_labor_cents": actual_labor_cents, "actual_parts_cents": actual_parts_cents},
        tech_headers,
    ))


def winterize_system(system_id, technician_id, route_date="2026-10-01"):
    """Drive a WINTERIZATION work order to COMPLETED so season_state -> WINTERIZED."""
    complete_work_order_full(system_id, technician_id, job_type="WINTERIZATION",
                             actual_labor_cents=5000, actual_parts_cents=1000,
                             estimated_cost_cents=9000, route_date=route_date)


def winterize_then_startup_system(system_id, technician_id, route_date="2026-10-01"):
    """Take a DORMANT system to season_state=ACTIVE by completing a WINTERIZATION
    (-> WINTERIZED) then a STARTUP (-> ACTIVE) work order. Reuses one route across both."""
    tech_headers = make_technician_headers(technician_id)
    route = create_route(technician_id, route_date=route_date)

    # WINTERIZATION
    wint = create_work_order(system_id, job_type="WINTERIZATION",
                             estimated_minutes=30, estimated_cost_cents=9000)
    route = create_route_stop(route["id"], wint["id"], route["version"],
                              arrival_start_sec=28800, window_minutes=60)
    get_success_data(api.depart_work_order(wint["id"], tech_headers))
    get_success_data(api.arrive_work_order(wint["id"], tech_headers))
    get_success_data(api.complete_work_order(
        wint["id"], {"actual_labor_cents": 5000, "actual_parts_cents": 1000}, tech_headers))

    # STARTUP (now allowed because season_state == WINTERIZED)
    start = create_work_order(system_id, job_type="STARTUP",
                              estimated_minutes=30, estimated_cost_cents=6000)
    route_now = get_success_data(api.get_route(route["id"], DISPATCHER))
    create_route_stop(route["id"], start["id"], route_now["version"],
                      arrival_start_sec=32400, window_minutes=60)
    get_success_data(api.depart_work_order(start["id"], tech_headers))
    get_success_data(api.arrive_work_order(start["id"], tech_headers))
    get_success_data(api.complete_work_order(
        start["id"], {"actual_labor_cents": 4000, "actual_parts_cents": 0}, tech_headers))


# ---------------------------------------------------------------------------
# Tier 3b: quote lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_quote(property_id, quote_type, line_items):
    return get_success_data(api.create_quote(
        {"property_id": property_id, "quote_type": quote_type, "line_items": line_items},
        DISPATCHER,
    ))


def setup_sent_quote(property_id, quote_type="INSTALL",
                     line_items=None):
    """Returns a quote that has been moved DRAFT -> SENT."""
    if line_items is None:
        line_items = [{"description": "heads", "quantity": 1, "unit_rate_cents": 5000}]
    quote = create_quote(property_id, quote_type, line_items)
    get_success_data(api.send_quote(quote["id"], DISPATCHER))
    return get_success_data(api.get_quote(quote["id"], DISPATCHER))


def setup_approved_quote_workorder(customer_id, property_id, quote_type="REPAIR",
                                   line_items=None):
    """Create a SENT quote and approve it as the owning customer; returns
    (quote_after_approve, work_order_id)."""
    quote = setup_sent_quote(property_id, quote_type=quote_type, line_items=line_items)
    cust_headers = make_customer_headers(customer_id)
    approved = get_success_data(api.approve_quote(quote["id"], cust_headers))
    return approved, approved["linked_work_order_id"]


# ---------------------------------------------------------------------------
# Tier 3c: backflow readiness
# ---------------------------------------------------------------------------
def setup_backflow_ready(static_psi=60, has_backflow_device=True, certified=True):
    """Returns (property, system, tester_technician) ready for a backflow test."""
    cust = create_customer(company_name="BF Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=static_psi, has_backflow_device=has_backflow_device)
    tester = create_technician(full_name="BF Tester", backflow_certified=certified)
    return prop, sys, tester


def record_backflow_test(system_id, tester_id, relief_open_psi, checkvalve_hold_psi):
    """Record a backflow test acting as the certified tester. Returns the test data."""
    headers = make_backflow_tester_headers(tester_id)
    return get_success_data(api.create_backflow_test(
        {"system_id": system_id, "tester_technician_id": tester_id,
         "relief_open_psi": relief_open_psi, "checkvalve_hold_psi": checkvalve_hold_psi},
        headers,
    ))


# ---------------------------------------------------------------------------
# Tier 4: route capacity targeting
# ---------------------------------------------------------------------------
def fill_route_with_stops(system_id, technician_id, n_stops, route_date="2026-05-03",
                          window_minutes=10, start_spacing_sec=3600, first_start_sec=0):
    """Create a route and place `n_stops` non-overlapping SCHEDULED stops on it,
    threading expected_route_version through each add. Each stop references its own
    fresh work order. Returns (route_id, last_route_version, work_order_ids)."""
    route = create_route(technician_id, route_date=route_date)
    route_id = route["id"]
    version = route["version"]
    wo_ids = []
    for i in range(n_stops):
        wo = create_work_order(system_id, job_type="HEAD_REPAIR",
                               estimated_minutes=10, estimated_cost_cents=1000)
        wo_ids.append(wo["id"])
        route_after = create_route_stop(
            route_id, wo["id"], version,
            arrival_start_sec=first_start_sec + i * start_spacing_sec,
            window_minutes=window_minutes,
        )
        version = route_after["version"]
    return route_id, version, wo_ids


# ---------------------------------------------------------------------------
# Tier 5: program lifecycle
# ---------------------------------------------------------------------------
def create_program(system_id, slots):
    return get_success_data(api.create_program(
        {"system_id": system_id, "slots": slots}, DISPATCHER,
    ))


def setup_active_season_system_with_zones(zone_specs, route_date="2026-10-02"):
    """Build a system whose season_state is ACTIVE (via winterize+startup) with the
    given zones MAPPED. zone_specs is a list of dicts merged into create_zone kwargs
    (must include zone_number). Returns (system, technician, zones)."""
    cust = create_customer(company_name="ActiveSeason Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=60)
    tech = create_technician(full_name="Season Tech")
    zones = [create_zone(sys["id"], **spec) for spec in zone_specs]
    winterize_then_startup_system(sys["id"], tech["id"], route_date=route_date)
    return sys, tech, zones
