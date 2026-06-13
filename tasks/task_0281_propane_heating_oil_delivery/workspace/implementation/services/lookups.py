"""Existence lookups (raise ERR_NOT_FOUND) and serialization to public dicts."""
import db
import errors


def _get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Resource not found")
    return rec


def get_account(account_id):
    return _get_or_404(db.accounts, account_id)


def get_price_plan(plan_id):
    return _get_or_404(db.price_plans, plan_id)


def get_tank(tank_id):
    return _get_or_404(db.tanks, tank_id)


def get_reading(reading_id):
    return _get_or_404(db.tank_readings, reading_id)


def get_market_price(market_price_id):
    return _get_or_404(db.market_prices, market_price_id)


def get_lease(lease_id):
    return _get_or_404(db.tank_leases, lease_id)


def get_inspection(inspection_id):
    return _get_or_404(db.safety_inspections, inspection_id)


def get_truck(truck_id):
    return _get_or_404(db.trucks, truck_id)


def get_route(route_id):
    return _get_or_404(db.routes, route_id)


def get_order(order_id):
    return _get_or_404(db.delivery_orders, order_id)


def get_budget_plan(budget_plan_id):
    return _get_or_404(db.budget_plans, budget_plan_id)


# --- Tank helpers ---
def latest_inspection(tank_id):
    """Most recent SafetyInspection for a tank, by inspected_at (then created_at)."""
    from clock import parse_iso
    best = None
    best_key = None
    for insp in db.safety_inspections.values():
        if insp.get("tank_id") != tank_id:
            continue
        idt = parse_iso(insp.get("inspected_at"))
        key = (idt, insp.get("created_at", ""))
        if best is None or key > best_key:
            best = insp
            best_key = key
    return best


def active_price_plan(account_id):
    for pp in db.price_plans.values():
        if pp.get("account_id") == account_id and pp.get("status") == "ACTIVE":
            return pp
    return None


def active_market_price(region_code, fuel_type):
    for mp in db.market_prices.values():
        if (mp.get("region_code") == region_code
                and mp.get("fuel_type") == fuel_type
                and mp.get("status") == "ACTIVE"):
            return mp
    return None


def active_budget_plan(account_id):
    for bp in db.budget_plans.values():
        if bp.get("account_id") == account_id and bp.get("status") == "ACTIVE":
            return bp
    return None


def orders_for_account(account_id):
    return [o for o in db.delivery_orders.values() if o.get("account_id") == account_id]


def orders_for_tank(tank_id):
    return [o for o in db.delivery_orders.values() if o.get("tank_id") == tank_id]


def orders_for_route(route_id):
    return [o for o in db.delivery_orders.values() if o.get("route_id") == route_id]


def leases_for_tank(tank_id):
    return [lease for lease in db.tank_leases.values() if lease.get("tank_id") == tank_id]


def tanks_for_account(account_id):
    return [t for t in db.tanks.values() if t.get("account_id") == account_id]


# ---------------------------------------------------------------------------
# Serialization: each entity returns the exact public field set.
# ---------------------------------------------------------------------------
_FULL_QUARTET = ("id", "created_at", "updated_at", "version")
_LEAN_PAIR = ("id", "created_at")


def _pick(rec, ordered_fields):
    return {f: rec.get(f) for f in ordered_fields}


def serialize_account(r):
    return _pick(r, _FULL_QUARTET + (
        "customer_name", "region_code", "fuel_type", "service_status",
        "credit_balance_cents", "active_price_plan_id",
    ))


def serialize_price_plan(r):
    return _pick(r, _FULL_QUARTET + (
        "account_id", "plan_type", "locked_price_cents_per_gallon",
        "cap_price_cents_per_gallon", "status", "effective_from",
    ))


def serialize_tank(r):
    return _pick(r, _FULL_QUARTET + (
        "account_id", "capacity_gallons", "current_gallons",
        "reorder_threshold_pct", "k_factor", "delivery_mode",
        "monitor_installed", "last_delivery_at", "last_reading_at",
        "service_status", "reorder_status",
    ))


def serialize_reading(r):
    return _pick(r, _LEAN_PAIR + ("tank_id", "reading_gallons", "read_at"))


def serialize_degree_day(r):
    return _pick(r, _LEAN_PAIR + ("region_code", "reading_date", "heating_degree_days"))


def serialize_market_price(r):
    return _pick(r, _FULL_QUARTET + (
        "region_code", "fuel_type", "market_price_cents_per_gallon", "status",
    ))


def serialize_lease(r):
    return _pick(r, _FULL_QUARTET + (
        "tank_id", "monthly_rent_cents", "lease_start", "lease_end", "status",
    ))


def serialize_inspection(r):
    return _pick(r, _FULL_QUARTET + (
        "tank_id", "result", "inspected_at", "notes",
    ))


def serialize_truck(r):
    return _pick(r, _FULL_QUARTET + (
        "region_code", "daily_capacity_gallons", "turnaround_buffer_minutes",
    ))


def serialize_route(r):
    return _pick(r, _FULL_QUARTET + (
        "truck_id", "route_date", "window_start", "window_end", "status",
        "reserved_gallons",
    ))


def serialize_order(r):
    return _pick(r, _FULL_QUARTET + (
        "account_id", "tank_id", "route_id", "origin", "requested_gallons",
        "priority", "status", "delivered_gallons", "price_cents_per_gallon",
        "invoice_total_cents", "budget_plan_id",
    ))


def serialize_budget_plan(r):
    return _pick(r, _FULL_QUARTET + (
        "account_id", "plan_year_start", "estimated_annual_gallons",
        "estimated_price_cents_per_gallon", "monthly_installment_cents",
        "installments_paid_count", "actual_cost_to_date_cents", "status",
        "settlement_balance_cents",
    ))
