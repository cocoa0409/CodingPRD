"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures. Every
ownership-gated call threads the actual entity id through make_*_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_fleet_manager_headers,
    make_driver_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


# ─── Atomic builders ───────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    return api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)


def post_fuel_price(fuel_type="REGULAR", zone="ZONE_A", price_per_gallon_cents=419,
                    effective_date="2026-04-01T00:00:00Z"):
    return get_success_data(api_client.create_fuel_price(
        {"fuel_type": fuel_type, "zone": zone,
         "price_per_gallon_cents": price_per_gallon_cents,
         "effective_date": effective_date}, ADMIN))


def new_customer(customer_type="INDIVIDUAL", name="Cust", email="cust@x.com"):
    return get_success_data(api_client.create_customer(
        {"name": name, "email": email, "customer_type": customer_type}, ADMIN))


def new_membership(customer_id, tier="PLUS", monthly_fee_cents=3999,
                   included_deliveries=5, price_lock_enabled=None):
    payload = {"customer_id": customer_id, "tier": tier,
               "monthly_fee_cents": monthly_fee_cents,
               "included_deliveries": included_deliveries}
    if price_lock_enabled is not None:
        payload["price_lock_enabled"] = price_lock_enabled
    return get_success_data(api_client.create_membership(
        payload, make_member_headers(customer_id)))


def new_fleet_account(customer_id, monthly_budget_cap_cents=100000,
                      allowed_fuel_types=None, allowed_addons=None):
    return get_success_data(api_client.create_fleet_account(
        {"customer_id": customer_id,
         "monthly_budget_cap_cents": monthly_budget_cap_cents,
         "allowed_fuel_types": allowed_fuel_types or ["REGULAR"],
         "allowed_addons": allowed_addons or []},
        make_fleet_manager_headers(customer_id)))


def new_vehicle(customer_id, fuel_type="REGULAR", tank_capacity_gallons=40,
                current_fuel_level_gallons=0, fleet_account_id=None,
                monthly_spend_cap_cents=None, make_model="Test", as_fleet=False):
    payload = {"customer_id": customer_id, "make_model": make_model,
               "fuel_type": fuel_type, "tank_capacity_gallons": tank_capacity_gallons,
               "current_fuel_level_gallons": current_fuel_level_gallons}
    if fleet_account_id is not None:
        payload["fleet_account_id"] = fleet_account_id
    if monthly_spend_cap_cents is not None:
        payload["monthly_spend_cap_cents"] = monthly_spend_cap_cents
    headers = make_fleet_manager_headers(customer_id) if as_fleet else make_member_headers(customer_id)
    return get_success_data(api_client.create_vehicle(payload, headers))


def new_truck(plate="TRK-1", home_zone="ZONE_A"):
    return get_success_data(api_client.create_truck(
        {"plate": plate, "home_zone": home_zone}, ADMIN))


def new_compartment(truck_id, fuel_type="REGULAR", gallons_capacity=200, gallons_onboard=100):
    return get_success_data(api_client.create_compartment(
        truck_id, {"fuel_type": fuel_type, "gallons_capacity": gallons_capacity,
                   "gallons_onboard": gallons_onboard}, ADMIN))


def new_route(truck_id, assigned_driver_id="driver-1", zone="ZONE_A",
              window_start="2026-05-02T06:00:00Z", window_end="2026-05-02T20:00:00Z",
              max_stops=None):
    payload = {"truck_id": truck_id, "assigned_driver_id": assigned_driver_id,
               "zone": zone, "window_start": window_start, "window_end": window_end}
    if max_stops is not None:
        payload["max_stops"] = max_stops
    return get_success_data(api_client.create_route(payload, DISPATCHER))


def new_order(customer_id, vehicle_id, zone="ZONE_A", requested_gallons=10,
              delivery_address="1 Main St",
              delivery_window_start="2026-05-02T09:00:00Z",
              delivery_window_end="2026-05-02T11:00:00Z",
              membership_id=None, fleet_account_id=None, is_priority=None,
              as_fleet=False):
    payload = {"customer_id": customer_id, "vehicle_id": vehicle_id, "zone": zone,
               "delivery_address": delivery_address, "requested_gallons": requested_gallons,
               "delivery_window_start": delivery_window_start,
               "delivery_window_end": delivery_window_end}
    if membership_id is not None:
        payload["membership_id"] = membership_id
    if fleet_account_id is not None:
        payload["fleet_account_id"] = fleet_account_id
    if is_priority is not None:
        payload["is_priority"] = is_priority
    headers = make_fleet_manager_headers(customer_id) if as_fleet else make_member_headers(customer_id)
    return get_success_data(api_client.create_order(payload, headers))


# ─── Refresh helpers (read-back current state) ─────────────────────────────

def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_vehicle(vehicle_id):
    return get_success_data(api_client.get_vehicle(vehicle_id, ADMIN))


def get_fleet_account(fleet_account_id):
    return get_success_data(api_client.get_fleet_account(fleet_account_id, ADMIN))


def get_membership(membership_id):
    return get_success_data(api_client.get_membership(membership_id, ADMIN))


def get_route(route_id):
    return get_success_data(api_client.get_route(route_id, ADMIN))


def get_compartment(truck_id, compartment_id):
    comps, _ = _list_data(api_client.list_compartments(truck_id, ADMIN))
    for c in comps:
        if c["id"] == compartment_id:
            return c
    raise AssertionError(f"Setup failed: compartment {compartment_id} not found on truck {truck_id}")


def _list_data(response):
    """Return (data_list, meta) leniently from a list response envelope."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta


# ─── Lifecycle shortcuts ───────────────────────────────────────────────────

def assign(order_id, route_id):
    return get_success_data(api_client.assign_route(order_id, {"route_id": route_id}, DISPATCHER))


def dispatch(route_id):
    return get_success_data(api_client.dispatch_route(route_id, DISPATCHER))


def arrive(order_id, driver_id):
    return get_success_data(api_client.arrive_order(order_id, make_driver_headers(driver_id)))


def deliver(order_id, dispensed_gallons, driver_id):
    return get_success_data(api_client.deliver_order(
        order_id, {"dispensed_gallons": dispensed_gallons}, make_driver_headers(driver_id)))


def drive_order_to_arrived(order_id, route_id, driver_id):
    """assign-route -> dispatch route -> driver arrive. Order ends ARRIVED."""
    assign(order_id, route_id)
    dispatch(route_id)
    arrive(order_id, driver_id)


# ─── Composite scenario fixtures (mirror the design-index setup chains) ─────

def setup_member_order_arrived(driver_id="driver-1", included_deliveries=5,
                               price_lock_enabled=True, requested_gallons=12,
                               is_priority=None, tank_capacity_gallons=40):
    """REGULAR/ZONE_A price 419; member (price-lock) + vehicle; truck+route;
    member order driven to ARRIVED. Returns a context dict."""
    post_fuel_price()
    cust = new_customer(name="Ada Member", email="ada@x.com")
    mem = new_membership(cust["id"], included_deliveries=included_deliveries,
                         price_lock_enabled=price_lock_enabled)
    veh = new_vehicle(cust["id"], tank_capacity_gallons=tank_capacity_gallons)
    truck = new_truck(plate="TRK-A")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id=driver_id, max_stops=4)
    order = new_order(cust["id"], veh["id"], membership_id=mem["id"],
                      requested_gallons=requested_gallons, is_priority=is_priority)
    drive_order_to_arrived(order["id"], route["id"], driver_id)
    return {"customer_id": cust["id"], "membership_id": mem["id"], "vehicle_id": veh["id"],
            "truck_id": truck["id"], "compartment_id": comp["id"], "route_id": route["id"],
            "order_id": order["id"], "driver_id": driver_id, "order": order}


def setup_dual_variant_fuel_cost_arrived(driver_id="driver-1"):
    """REGULAR/ZONE_A 419 (eff 2026-04-01) + a later 439 (eff 2026-05-15); member with
    price_lock_enabled=true + REGULAR vehicle; member order requested 12 gal driven to
    ARRIVED; clock then advanced to 2026-05-20 (after the 439 price). Ready for deliver."""
    post_fuel_price(fuel_type="REGULAR", price_per_gallon_cents=419,
                    effective_date="2026-04-01T00:00:00Z")
    post_fuel_price(fuel_type="REGULAR", price_per_gallon_cents=439,
                    effective_date="2026-05-15T00:00:00Z")
    cust = new_customer(name="Ada Member", email="ada@x.com")
    mem = new_membership(cust["id"], included_deliveries=5, price_lock_enabled=True)
    veh = new_vehicle(cust["id"], tank_capacity_gallons=40, make_model="Civic")
    truck = new_truck(plate="TRK-1")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id=driver_id, max_stops=4)
    order = new_order(cust["id"], veh["id"], membership_id=mem["id"], requested_gallons=12,
                      delivery_address="1 Main St")
    drive_order_to_arrived(order["id"], route["id"], driver_id)
    set_clock("2026-05-20T00:00:00Z")
    return {"customer_id": cust["id"], "membership_id": mem["id"], "vehicle_id": veh["id"],
            "order_id": order["id"], "driver_id": driver_id, "order": order}


def setup_membership_unused_credit():
    """Individual customer + ACTIVE membership (fee 3999, included 5, used 0).
    Returns (customer_id, membership)."""
    cust = new_customer(name="Ben Member", email="ben@x.com")
    mem = new_membership(cust["id"], monthly_fee_cents=3999, included_deliveries=5)
    return cust["id"], mem


def setup_member_order_with_carwash():
    """REGULAR price; member + vehicle; SCHEDULED member order with a CAR_WASH add-on.
    Returns context including the car-wash add-on line."""
    post_fuel_price()
    cust = new_customer(name="Dee Member", email="dee@x.com")
    mem = new_membership(cust["id"], included_deliveries=5)
    veh = new_vehicle(cust["id"], make_model="Prius")
    order = new_order(cust["id"], veh["id"], membership_id=mem["id"], requested_gallons=8)
    cw = get_success_data(api_client.add_addon(
        order["id"], {"addon_type": "CAR_WASH"}, make_member_headers(cust["id"])))
    return {"customer_id": cust["id"], "membership_id": mem["id"], "vehicle_id": veh["id"],
            "order_id": order["id"], "car_wash": cw}


def setup_order_unable_to_access(driver_id="driver-3"):
    """Per-fill order driven to ARRIVED then report-unable-access (=> UNABLE_TO_ACCESS)."""
    post_fuel_price()
    cust = new_customer(name="Eve Ind", email="eve@x.com")
    veh = new_vehicle(cust["id"], make_model="Golf")
    truck = new_truck(plate="TRK-3")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id=driver_id)
    order = new_order(cust["id"], veh["id"], requested_gallons=8)
    drive_order_to_arrived(order["id"], route["id"], driver_id)
    get_success_data(api_client.report_unable_access(order["id"], make_driver_headers(driver_id)))
    return {"customer_id": cust["id"], "vehicle_id": veh["id"], "order_id": order["id"],
            "compartment_id": comp["id"], "truck_id": truck["id"], "driver_id": driver_id}


def setup_paused_membership():
    """Individual customer with an ACTIVE membership that has been paused once."""
    cust = new_customer(name="Finn Ind", email="finn@x.com")
    mem = new_membership(cust["id"], tier="BASIC", monthly_fee_cents=1999, included_deliveries=2)
    get_success_data(api_client.pause_membership(mem["id"], make_member_headers(cust["id"])))
    return {"customer_id": cust["id"], "membership_id": mem["id"]}


def setup_fleet_single_vehicle_order_arrived(driver_id="driver-4"):
    """DIESEL fleet: account budget 100000 (allowed DIESEL), single vehicle cap 5790;
    one fleet order (10 gal, est_total 5790) driven to ARRIVED."""
    post_fuel_price(fuel_type="DIESEL", price_per_gallon_cents=459)
    cust = new_customer(customer_type="FLEET", name="GreenFleet", email="ops@greenfleet.com")
    fa = new_fleet_account(cust["id"], monthly_budget_cap_cents=100000,
                           allowed_fuel_types=["DIESEL"])
    veh = new_vehicle(cust["id"], fuel_type="DIESEL", tank_capacity_gallons=100,
                      fleet_account_id=fa["id"], monthly_spend_cap_cents=5790,
                      make_model="F250", as_fleet=True)
    truck = new_truck(plate="TRK-4")
    comp = new_compartment(truck["id"], fuel_type="DIESEL")
    route = new_route(truck["id"], assigned_driver_id=driver_id)
    order = new_order(cust["id"], veh["id"], fleet_account_id=fa["id"],
                      requested_gallons=10, delivery_address="9 Depot Rd", as_fleet=True)
    drive_order_to_arrived(order["id"], route["id"], driver_id)
    return {"customer_id": cust["id"], "fleet_account_id": fa["id"], "vehicle_id": veh["id"],
            "order_id": order["id"], "compartment_id": comp["id"], "driver_id": driver_id}


def setup_member_order_routed():
    """Member order (8 gal) assigned to a route (ROUTED), reserving 8 gal (available 92)."""
    post_fuel_price()
    cust = new_customer(name="Gil Ind", email="gil@x.com")
    mem = new_membership(cust["id"], included_deliveries=5)
    veh = new_vehicle(cust["id"], make_model="A4")
    truck = new_truck(plate="TRK-5")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id="driver-5")
    order = new_order(cust["id"], veh["id"], membership_id=mem["id"], requested_gallons=8)
    assign(order["id"], route["id"])
    return {"customer_id": cust["id"], "membership_id": mem["id"], "vehicle_id": veh["id"],
            "order_id": order["id"], "compartment_id": comp["id"], "truck_id": truck["id"]}


def setup_perfill_order_routed():
    """Individual customer + REGULAR vehicle; truck REGULAR compartment onboard 100 on a
    PLANNING ZONE_A route; a per-fill order (8 gal) assigned (ROUTED, reserving 8 gal so the
    compartment has 92 available). Returns ids."""
    post_fuel_price()
    cust = new_customer(name="Mia Ind", email="mia@x.com")
    veh = new_vehicle(cust["id"], make_model="T-Roc")
    truck = new_truck(plate="TRK-9")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id="driver-9")
    order = new_order(cust["id"], veh["id"], requested_gallons=8, delivery_address="8 Rsv St")
    assign(order["id"], route["id"])
    return {"customer_id": cust["id"], "vehicle_id": veh["id"], "order_id": order["id"],
            "compartment_id": comp["id"], "truck_id": truck["id"], "route_id": route["id"]}


def setup_fleet_two_vehicles(target_cap_cents=100, other_cap_cents=100000, suspend_target=True):
    """FLEET account (budget 100000, allowed REGULAR) with TWO REGULAR vehicles; the
    first (target) has target_cap_cents; optionally suspend it (account stays ACTIVE)."""
    post_fuel_price()
    cust = new_customer(customer_type="FLEET", name="BlueFleet", email="ops@bluefleet.com")
    fa = new_fleet_account(cust["id"], monthly_budget_cap_cents=100000,
                           allowed_fuel_types=["REGULAR"])
    veh_a = new_vehicle(cust["id"], fleet_account_id=fa["id"], make_model="Van A",
                        monthly_spend_cap_cents=target_cap_cents, as_fleet=True)
    veh_b = new_vehicle(cust["id"], fleet_account_id=fa["id"], make_model="Van B",
                        monthly_spend_cap_cents=other_cap_cents, as_fleet=True)
    if suspend_target:
        get_success_data(api_client.suspend_vehicle(
            veh_a["id"], make_fleet_manager_headers(cust["id"])))
    return {"customer_id": cust["id"], "fleet_account_id": fa["id"],
            "vehicle_a": veh_a["id"], "vehicle_b": veh_b["id"]}


def setup_vehicle_with_scheduled_order(tank_capacity_gallons=40, current_fuel_level_gallons=0,
                                       requested_gallons=5,
                                       window_start="2026-05-02T09:00:00Z",
                                       window_end="2026-05-02T10:00:00Z",
                                       make_model="Jetta"):
    """Individual customer + REGULAR vehicle; one SCHEDULED per-fill order in the given window."""
    post_fuel_price()
    cust = new_customer(name="Hal Ind", email="hal@x.com")
    veh = new_vehicle(cust["id"], tank_capacity_gallons=tank_capacity_gallons,
                      current_fuel_level_gallons=current_fuel_level_gallons, make_model=make_model)
    order = new_order(cust["id"], veh["id"], requested_gallons=requested_gallons,
                      delivery_window_start=window_start, delivery_window_end=window_end)
    return {"customer_id": cust["id"], "vehicle_id": veh["id"], "order_id": order["id"]}


def setup_individual_vehicle(tank_capacity_gallons=15, current_fuel_level_gallons=3,
                             name="Ivy Ind", email="ivy@x.com", make_model="Passat"):
    """Individual customer + REGULAR vehicle with the given tank/level. Returns ids."""
    post_fuel_price()
    cust = new_customer(name=name, email=email)
    veh = new_vehicle(cust["id"], tank_capacity_gallons=tank_capacity_gallons,
                      current_fuel_level_gallons=current_fuel_level_gallons, make_model=make_model)
    return {"customer_id": cust["id"], "vehicle_id": veh["id"]}


def setup_route_at_capacity(driver_id="driver-6"):
    """Two REGULAR vehicles; PLANNING ZONE_A route with max_stops=1; order A already
    assigned (stop_count 1); order B still SCHEDULED. Returns ids."""
    post_fuel_price()
    cust = new_customer(name="Jo Ind", email="jo@x.com")
    veh_a = new_vehicle(cust["id"], make_model="Car A")
    veh_b = new_vehicle(cust["id"], make_model="Car B")
    truck = new_truck(plate="TRK-6")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id=driver_id, max_stops=1)
    ord_a = new_order(cust["id"], veh_a["id"], requested_gallons=5, delivery_address="A St",
                      delivery_window_start="2026-05-02T09:00:00Z",
                      delivery_window_end="2026-05-02T10:00:00Z")
    ord_b = new_order(cust["id"], veh_b["id"], requested_gallons=5, delivery_address="B St",
                      delivery_window_start="2026-05-02T12:00:00Z",
                      delivery_window_end="2026-05-02T13:00:00Z")
    assign(ord_a["id"], route["id"])
    return {"customer_id": cust["id"], "route_id": route["id"],
            "order_a": ord_a["id"], "order_b": ord_b["id"]}


def setup_planning_route_truck_maintenance(driver_id="driver-7"):
    """PLANNING ZONE_A route with one assigned order; truck then set to MAINTENANCE."""
    post_fuel_price()
    cust = new_customer(name="Ken Ind", email="ken@x.com")
    veh = new_vehicle(cust["id"], make_model="Fox")
    truck = new_truck(plate="TRK-7")
    comp = new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id=driver_id)
    order = new_order(cust["id"], veh["id"], requested_gallons=5,
                      delivery_window_start="2026-05-02T09:00:00Z",
                      delivery_window_end="2026-05-02T10:00:00Z")
    assign(order["id"], route["id"])
    get_success_data(api_client.set_truck_maintenance(truck["id"], {"in_maintenance": True}, ADMIN))
    return {"customer_id": cust["id"], "route_id": route["id"], "truck_id": truck["id"],
            "order_id": order["id"]}


def setup_truck_with_route(window_start="2026-05-02T08:00:00Z",
                           window_end="2026-05-02T12:00:00Z", driver_id="driver-8"):
    """One truck with an existing PLANNING route in the given window (ZONE_A)."""
    truck = new_truck(plate="TRK-8")
    route = new_route(truck["id"], assigned_driver_id=driver_id,
                      window_start=window_start, window_end=window_end)
    return {"truck_id": truck["id"], "route_id": route["id"], "driver_id": driver_id}


def setup_fleet_order_scheduled():
    """DIESEL fleet: account budget 100000 (allowed DIESEL), vehicle cap 100000;
    one SCHEDULED fleet order (10 gal, est_total 5790). Returns ids."""
    post_fuel_price(fuel_type="DIESEL", price_per_gallon_cents=459)
    cust = new_customer(customer_type="FLEET", name="GoldFleet", email="ops@goldfleet.com")
    fa = new_fleet_account(cust["id"], monthly_budget_cap_cents=100000,
                           allowed_fuel_types=["DIESEL"])
    veh = new_vehicle(cust["id"], fuel_type="DIESEL", tank_capacity_gallons=100,
                      fleet_account_id=fa["id"], monthly_spend_cap_cents=100000,
                      make_model="Sprinter", as_fleet=True)
    order = new_order(cust["id"], veh["id"], fleet_account_id=fa["id"], requested_gallons=10,
                      delivery_address="9 Depot Rd", as_fleet=True)
    return {"customer_id": cust["id"], "fleet_account_id": fa["id"], "vehicle_id": veh["id"],
            "order_id": order["id"]}


def setup_fleet_account(name="OccFleet", email="ops@occfleet.com"):
    """FLEET customer + FleetAccount (version 1). Returns (customer_id, fleet_account)."""
    cust = new_customer(customer_type="FLEET", name=name, email=email)
    fa = new_fleet_account(cust["id"], monthly_budget_cap_cents=100000,
                           allowed_fuel_types=["REGULAR"])
    return cust["id"], fa
