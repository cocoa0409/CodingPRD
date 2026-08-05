"""Shared domain lookups, order pricing math, and budget/reservation ledgers."""
import store
from store import DB
from core import ApiError, money_mul, round_half_up, touch, g1

NON_TERMINAL_ORDER = {"SCHEDULED", "ROUTED", "EN_ROUTE", "ARRIVED", "UNABLE_TO_ACCESS"}


# ---------------------------------------------------------------------------
# Existence lookups (raise the scaffold-specified not-found error)
# ---------------------------------------------------------------------------
def get_customer(cid):
    c = DB.customers.get(cid)
    if not c:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    return c


def get_membership(mid):
    m = DB.memberships.get(mid)
    if not m:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND", "Membership not found")
    return m


def get_fleet_account(fid):
    f = DB.fleet_accounts.get(fid)
    if not f:
        raise ApiError("ERR_FLEET_ACCOUNT_NOT_FOUND", "Fleet account not found")
    return f


def get_vehicle(vid):
    v = DB.vehicles.get(vid)
    if not v:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", "Vehicle not found")
    return v


def get_truck(tid):
    t = DB.trucks.get(tid)
    if not t:
        raise ApiError("ERR_TRUCK_NOT_FOUND", "Truck not found")
    return t


def get_compartment_of_truck(truck_id, comp_id):
    c = DB.compartments.get(comp_id)
    if not c or c["truck_id"] != truck_id:
        raise ApiError("ERR_COMPARTMENT_NOT_FOUND", "Compartment not found")
    return c


def get_route(rid):
    r = DB.routes.get(rid)
    if not r:
        raise ApiError("ERR_ROUTE_NOT_FOUND", "Route not found")
    return r


def get_order(oid):
    o = DB.orders.get(oid)
    if not o:
        raise ApiError("ERR_ORDER_NOT_FOUND", "Order not found")
    return o


# ---------------------------------------------------------------------------
# Order pricing (PRD §3.4, §3.6, §3.7)
# ---------------------------------------------------------------------------
def compute_service_fee(order, membership):
    """Tiered delivery fee (reads deliveries_used BEFORE this order's increment)."""
    if membership is not None:
        if membership["deliveries_used_this_period"] < membership["included_deliveries"]:
            base = 0
        else:
            base = store.MEMBER_OVERAGE_FEE_CENTS
    else:
        base = store.BASE_DELIVERY_FEE_CENTS
    surcharge = store.PRIORITY_SURCHARGE_CENTS if order["is_priority"] else 0
    return base + surcharge


def membership_discount(gallons, membership):
    if membership is None:
        return 0
    return money_mul(gallons, store.MEMBER_DISCOUNT_PER_GALLON_CENTS)


def recompute_estimate(order, membership):
    """Recompute the provisional estimated_total from stored component lines."""
    disc = membership_discount(order["requested_gallons"], membership)
    order["membership_discount_cents"] = disc
    total = (order["estimated_fuel_cost_cents"]
             + order["service_fee_cents"]
             + order["addon_total_cents"]
             - disc)
    order["estimated_total_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Budget ledger (PRD §2.7)
# ---------------------------------------------------------------------------
def commit_budget(order, amount, membership_touch=None):
    """Reserve `amount` into committed buckets of the vehicle (+ fleet account)."""
    v = DB.vehicles[order["vehicle_id"]]
    v["committed_spend_cents"] += amount
    touch(v)
    if order["fleet_account_id"]:
        f = DB.fleet_accounts[order["fleet_account_id"]]
        f["committed_budget_cents"] += amount
        touch(f)


def release_commit(order, amount):
    v = DB.vehicles[order["vehicle_id"]]
    v["committed_spend_cents"] -= amount
    touch(v)
    if order["fleet_account_id"]:
        f = DB.fleet_accounts[order["fleet_account_id"]]
        f["committed_budget_cents"] -= amount
        touch(f)


# ---------------------------------------------------------------------------
# Compartment reservation ledger (PRD §2.7)
# ---------------------------------------------------------------------------
def release_reservation(order):
    comp_id = order.get("_compartment_id")
    if not comp_id:
        return
    comp = DB.compartments.get(comp_id)
    if comp:
        comp["gallons_reserved"] = g1(comp["gallons_reserved"] - order["requested_gallons"])
        touch(comp)
    order["_compartment_id"] = None
