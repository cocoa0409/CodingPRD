"""Entity -> JSON serializers. Computed fields are derived here; internal
bookkeeping keys (prefixed '_') are never emitted."""
from core import fmt_dt, g1


def ser_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "email": c["email"],
        "customer_type": c["customer_type"],
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_membership(m):
    return {
        "id": m["id"],
        "customer_id": m["customer_id"],
        "tier": m["tier"],
        "monthly_fee_cents": m["monthly_fee_cents"],
        "included_deliveries": m["included_deliveries"],
        "price_lock_enabled": m["price_lock_enabled"],
        "deliveries_used_this_period": m["deliveries_used_this_period"],
        "status": m["status"],
        "current_period_start": fmt_dt(m["current_period_start"]),
        "current_period_end": fmt_dt(m["current_period_end"]),
        "estimated_next_charge_cents": m["estimated_next_charge_cents"],
        "final_settlement_charge_cents": m["final_settlement_charge_cents"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_fleet_account(f):
    remaining = f["monthly_budget_cap_cents"] - f["committed_budget_cents"] - f["settled_budget_cents"]
    return {
        "id": f["id"],
        "customer_id": f["customer_id"],
        "monthly_budget_cap_cents": f["monthly_budget_cap_cents"],
        "allowed_fuel_types": list(f["allowed_fuel_types"]),
        "allowed_addons": list(f["allowed_addons"]),
        "committed_budget_cents": f["committed_budget_cents"],
        "settled_budget_cents": f["settled_budget_cents"],
        "remaining_budget_cents": remaining,
        "active_vehicle_count": f["active_vehicle_count"],
        "suspended_vehicle_count": f["suspended_vehicle_count"],
        "status": f["status"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def ser_vehicle(v):
    remaining = v["monthly_spend_cap_cents"] - v["committed_spend_cents"] - v["settled_spend_cents"]
    return {
        "id": v["id"],
        "customer_id": v["customer_id"],
        "fleet_account_id": v["fleet_account_id"],
        "make_model": v["make_model"],
        "fuel_type": v["fuel_type"],
        "tank_capacity_gallons": g1(v["tank_capacity_gallons"]),
        "current_fuel_level_gallons": g1(v["current_fuel_level_gallons"]),
        "monthly_spend_cap_cents": v["monthly_spend_cap_cents"],
        "committed_spend_cents": v["committed_spend_cents"],
        "settled_spend_cents": v["settled_spend_cents"],
        "remaining_budget_cents": remaining,
        "status": v["status"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def ser_truck(t):
    return {
        "id": t["id"],
        "plate": t["plate"],
        "home_zone": t["home_zone"],
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_compartment(c):
    available = g1(c["gallons_onboard"] - c["gallons_reserved"])
    return {
        "id": c["id"],
        "truck_id": c["truck_id"],
        "fuel_type": c["fuel_type"],
        "gallons_capacity": g1(c["gallons_capacity"]),
        "gallons_onboard": g1(c["gallons_onboard"]),
        "gallons_reserved": g1(c["gallons_reserved"]),
        "gallons_available": available,
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_route(r):
    return {
        "id": r["id"],
        "truck_id": r["truck_id"],
        "assigned_driver_id": r["assigned_driver_id"],
        "zone": r["zone"],
        "window_start": fmt_dt(r["window_start"]),
        "window_end": fmt_dt(r["window_end"]),
        "max_stops": r["max_stops"],
        "stop_count": r["stop_count"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_order(o):
    def gg(x):
        return None if x is None else g1(x)
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "vehicle_id": o["vehicle_id"],
        "membership_id": o["membership_id"],
        "fleet_account_id": o["fleet_account_id"],
        "route_id": o["route_id"],
        "fuel_type": o["fuel_type"],
        "zone": o["zone"],
        "delivery_address": o["delivery_address"],
        "requested_gallons": g1(o["requested_gallons"]),
        "is_priority": o["is_priority"],
        "delivery_window_start": fmt_dt(o["delivery_window_start"]),
        "delivery_window_end": fmt_dt(o["delivery_window_end"]),
        "dispensed_gallons": gg(o["dispensed_gallons"]),
        "locked_price_per_gallon_cents": o["locked_price_per_gallon_cents"],
        "estimated_fuel_cost_cents": o["estimated_fuel_cost_cents"],
        "final_fuel_cost_cents": o["final_fuel_cost_cents"],
        "service_fee_cents": o["service_fee_cents"],
        "addon_total_cents": o["addon_total_cents"],
        "membership_discount_cents": o["membership_discount_cents"],
        "estimated_total_cents": o["estimated_total_cents"],
        "total_cost_cents": o["total_cost_cents"],
        "payment_status": o["payment_status"],
        "status": o["status"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def ser_addon(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "addon_type": a["addon_type"],
        "list_price_cents": a["list_price_cents"],
        "charged_price_cents": a["charged_price_cents"],
        "created_at": fmt_dt(a["created_at"]),
    }


def ser_fuel_price(p):
    return {
        "id": p["id"],
        "fuel_type": p["fuel_type"],
        "zone": p["zone"],
        "price_per_gallon_cents": p["price_per_gallon_cents"],
        "effective_date": fmt_dt(p["effective_date"]),
        "created_at": fmt_dt(p["created_at"]),
    }
