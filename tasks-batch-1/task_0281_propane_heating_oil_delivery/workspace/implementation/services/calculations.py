"""Pure calculation routines (SCAFFOLD 1.3 / PRD §3.2, §3.3, §3.6, §3.10).

All money is integer cents; all fuel is whole integer gallons. Division for
money rounds half up; consumption/percent figures floor.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import parse_iso

# delivery_price constants
VOL_TIER1_GALLONS = 150
VOL_TIER1_DISCOUNT_CENTS = 5
VOL_TIER2_GALLONS = 300
VOL_TIER2_DISCOUNT_CENTS = 12
MIN_FLOOR_CENTS = 50

# invoice_total constants
EMERGENCY_SURCHARGE_PCT = 10
OFF_ROUTE_FEE_CENTS = 2500

# tank_reorder_projection constant
K_FACTOR_SCALE = 1000


def round_half_up(numerator, denominator):
    """Integer round-half-up of numerator/denominator."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# tank_reorder_projection
# ---------------------------------------------------------------------------
def _hdd_since(region_code, baseline_at, clock_now):
    """Sum heating-degree-days in the half-open window [baseline_at, clock_now).

    Includes rows whose reading_date >= baseline_at AND reading_date < clock_now.
    """
    total = 0
    for ddr in db.degree_day_readings.values():
        if ddr.get("region_code") != region_code:
            continue
        rd = parse_iso(ddr.get("reading_date"))
        if rd is None:
            continue
        if rd >= baseline_at and rd < clock_now:
            total += ddr.get("heating_degree_days", 0)
    return total


def projected_gallons(tank, account, clock_now):
    """Return projected_gallons for a tank at clock_now using the correct variant.

    MONITOR_BASED variant: tank.monitor_installed is True AND a TankMonitorReading
      exists whose read_at is after tank.last_delivery_at -> baseline is that
      latest reading's reading_gallons / read_at.
    DEGREE_DAY_ESTIMATE variant (otherwise): baseline is tank.current_gallons /
      tank.last_delivery_at (falling back to tank.created_at when last_delivery_at
      is null).
    """
    last_delivery_at = tank.get("last_delivery_at")
    last_delivery_dt = parse_iso(last_delivery_at) if last_delivery_at else None

    baseline_gallons = None
    baseline_at = None

    if tank.get("monitor_installed"):
        # Find the most recent reading (by read_at) for this tank.
        latest = None
        latest_dt = None
        for r in db.tank_readings.values():
            if r.get("tank_id") != tank["id"]:
                continue
            rdt = parse_iso(r.get("read_at"))
            if rdt is None:
                continue
            if latest_dt is None or rdt > latest_dt:
                latest_dt = rdt
                latest = r
        # Monitor-based only if a reading exists whose read_at is after the
        # baseline anchor (tank.last_delivery_at). When last_delivery_at is null,
        # any reading qualifies as "after" the (absent) delivery anchor.
        if latest is not None and (last_delivery_dt is None or latest_dt > last_delivery_dt):
            baseline_gallons = latest.get("reading_gallons", 0)
            baseline_at = latest_dt

    if baseline_gallons is None:
        # DEGREE_DAY_ESTIMATE variant
        baseline_gallons = tank.get("current_gallons", 0)
        baseline_at = last_delivery_dt
        if baseline_at is None:
            baseline_at = parse_iso(tank.get("created_at"))

    hdd = _hdd_since(account.get("region_code"), baseline_at, clock_now)
    consumed = (tank.get("k_factor", 0) * hdd) // K_FACTOR_SCALE  # floor
    proj = baseline_gallons - consumed
    if proj < 0:
        proj = 0
    return proj


def reorder_status_for(tank, account, clock_now):
    """Compute reorder_status (OK|DUE) from the projection."""
    proj = projected_gallons(tank, account, clock_now)
    capacity = tank.get("capacity_gallons", 0)
    if capacity <= 0:
        projected_pct = 0
    else:
        projected_pct = (proj * 100) // capacity  # floor
    threshold = tank.get("reorder_threshold_pct", 30)
    return "DUE" if projected_pct <= threshold else "OK"


# ---------------------------------------------------------------------------
# monthly_installment
# ---------------------------------------------------------------------------
def monthly_installment(estimated_annual_gallons, estimated_price_cents_per_gallon):
    estimated_annual_cost = estimated_annual_gallons * estimated_price_cents_per_gallon
    return round_half_up(estimated_annual_cost, 12)


# ---------------------------------------------------------------------------
# budget_reconciliation (provisional settlement balance)
# ---------------------------------------------------------------------------
def settlement_balance(installments_paid_count, monthly_installment_cents,
                       actual_cost_to_date_cents):
    installments_funded = installments_paid_count * monthly_installment_cents
    return installments_funded - actual_cost_to_date_cents


# ---------------------------------------------------------------------------
# delivery_price
# ---------------------------------------------------------------------------
def delivery_price(plan, market_price_cpg, delivered_gallons):
    """Resolve effective price_cents_per_gallon for a delivery.

    plan: the ACTIVE PricePlan record.
    market_price_cpg: market_price_cents_per_gallon of the ACTIVE MarketPrice for
      (region, fuel); required for MARKET/CAP, ignored for FIXED.
    """
    plan_type = plan.get("plan_type")
    if plan_type == "FIXED":
        base = plan.get("locked_price_cents_per_gallon")
    elif plan_type == "MARKET":
        base = market_price_cpg
    elif plan_type == "CAP":
        base = min(plan.get("cap_price_cents_per_gallon"), market_price_cpg)
    else:
        base = market_price_cpg

    if delivered_gallons >= VOL_TIER2_GALLONS:
        discount = VOL_TIER2_DISCOUNT_CENTS
    elif delivered_gallons >= VOL_TIER1_GALLONS:
        discount = VOL_TIER1_DISCOUNT_CENTS
    else:
        discount = 0

    return max(MIN_FLOOR_CENTS, base - discount)


# ---------------------------------------------------------------------------
# invoice_total (per-line rounding, pinned order)
# ---------------------------------------------------------------------------
def invoice_total(delivered_gallons, price_cents_per_gallon, priority, origin):
    fuel_line = delivered_gallons * price_cents_per_gallon
    if priority == "EMERGENCY":
        emergency_surcharge = round_half_up(fuel_line * EMERGENCY_SURCHARGE_PCT, 100)
    else:
        emergency_surcharge = 0
    off_route_fee = OFF_ROUTE_FEE_CENTS if origin == "WILL_CALL" else 0
    return fuel_line + emergency_surcharge + off_route_fee
