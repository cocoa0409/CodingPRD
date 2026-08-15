"""Calculation rules (SCAFFOLD Table 3 / PRD §3)."""
from datetime import timedelta
from decimal import Decimal

from constants import (
    CONVERSION_DIVISOR,
    DUE_SOON_DAYS,
    FEE_FLAT_CENTS,
    FEE_TIER1_LIMIT,
    FEE_TIER2_LIMIT,
    FEE_TIER2_RATE,
    FEE_TIER3_RATE,
    GRADE_LIMITS_PPM,
    HOLD_RELEASE_RATIO,
    HYDRO_INTERVAL_MONTHS,
    LINE_LOSS_LITERS,
    MARGINAL_FACTOR,
    STANDARD_RESIDUAL_BAR,
    TIER1_LAST_DAY,
    TIER1_MULT,
    TIER2_LAST_DAY,
    TIER2_MULT,
    TIER3_MULT,
    TRUCK_CAPACITY_LITERS,
)
from db import store
from util import add_months, clock_date, dec, round0, round2


# ---- telemetry_level_reconciliation ----

def governing_reading(owner_field, owner_id):
    """Reading with greatest measured_at; ties broken by later created seq."""
    best = None
    for r in store.readings.values():
        if r.get(owner_field) != owner_id:
            continue
        if best is None:
            best = r
            continue
        if (r["measured_at_dt"], r["_seq"]) > (best["measured_at_dt"], best["_seq"]):
            best = r
    return best


def tank_current_level(tank):
    g = governing_reading("tank_id", tank["id"])
    if g is None:
        return Decimal("0")
    return round2(g["measured_level_liters"] - tank["drawn_liters"])


def installation_current_level(installation):
    g = governing_reading("installation_id", installation["id"])
    if g is None:
        return Decimal("0")
    return round2(g["measured_level_liters"])


def tank_low_level_flag(tank):
    return tank_current_level(tank) <= dec(tank["reorder_point_liters"])


# ---- hydro_status_derivation ----

def hydro_due_date(last_hydro_date, service_gas):
    return add_months(last_hydro_date, HYDRO_INTERVAL_MONTHS[service_gas])


def hydro_status(cylinder):
    due = cylinder["hydro_due_date_d"]
    days_to_due = (due - clock_date()).days
    if days_to_due < 0:
        return "OVERDUE"
    if days_to_due <= DUE_SOON_DAYS:
        return "DUE_SOON"
    return "COMPLIANT"


# ---- fill_draw_liters ----

def lot_reserved_cylinders(lot):
    return [
        c
        for c in store.cylinders.values()
        if c["status"] == "RESERVED" and c["current_fill_lot_id"] == lot["id"]
    ]


def fill_draw_liters(lot, residuals=None):
    """residuals: {cylinder_id: Decimal bar} for the FINAL variant, else None
    for PROVISIONAL (flat STANDARD_RESIDUAL_BAR)."""
    cyls = lot_reserved_cylinders(lot)
    if not cyls:
        return Decimal("0")
    total = Decimal("0")
    for c in cyls:
        if residuals is not None and c["id"] in residuals:
            residual = residuals[c["id"]]
        else:
            residual = STANDARD_RESIDUAL_BAR
        per = dec(c["water_capacity_liters"]) * (dec(lot["target_fill_pressure_bar"]) - residual) / CONVERSION_DIVISOR
        total += per
    total += LINE_LOSS_LITERS
    return round2(total)


# ---- demurrage_accrual ----

def _segment_days(first, last, lo, hi):
    a = max(first, lo)
    b = last if hi is None else min(last, hi)
    return max(0, b - a + 1)


def demurrage_cents(daily_rate_cents, first_index, last_index):
    """Tiered accrual over overdue day indices [first_index..last_index].
    Per tier segment round_half_up, then summed (never re-rounded)."""
    if last_index < first_index or last_index <= 0:
        return 0
    rate = dec(daily_rate_cents)
    total = 0
    d1 = _segment_days(first_index, last_index, 1, TIER1_LAST_DAY)
    if d1:
        total += round0(d1 * rate * TIER1_MULT)
    d2 = _segment_days(first_index, last_index, TIER1_LAST_DAY + 1, TIER2_LAST_DAY)
    if d2:
        total += round0(d2 * rate * TIER2_MULT)
    d3 = _segment_days(first_index, last_index, TIER2_LAST_DAY + 1, None)
    if d3:
        total += round0(d3 * rate * TIER3_MULT)
    return total


def demurrage_through(daily_rate_cents, overdue_days):
    return demurrage_cents(daily_rate_cents, 1, overdue_days)


# ---- rental_final_charge ----

def variant_base_cents(customer, daily_rate_cents, days):
    if customer["billing_variant"] == "GRACE_PERIOD":
        billable = max(0, days - customer["free_days"])
    else:  # CALENDAR_DAY
        billable = days
    return daily_rate_cents * billable


def rental_close_charge(rental, customer, cylinder, end_date, include_loss_fee=False):
    days_out = (end_date - rental["out_date_d"]).days
    overdue_days = max(0, (end_date - rental["due_date_d"]).days)
    base = variant_base_cents(customer, rental["daily_rate_cents"], days_out)
    dem = demurrage_through(rental["daily_rate_cents"], overdue_days)
    charge = base + dem - rental["demurrage_billed_cents"]
    if include_loss_fee:
        from constants import SIZE_SPECS

        charge += SIZE_SPECS[cylinder["size_code"]]["loss_fee_cents"]
    return max(0, charge)


# ---- blend_price_quote ----

def blend_price_quote(components, batch_qty_liters):
    component_cost = 0
    for comp in components:
        contribution = dec(comp["target_pct"]) / Decimal("100") * dec(batch_qty_liters) * dec(comp["unit_cost_cents_per_liter"])
        component_cost += round0(contribution)
    if component_cost < FEE_TIER1_LIMIT:
        fee = FEE_FLAT_CENTS
    elif component_cost < FEE_TIER2_LIMIT:
        fee = round0(dec(component_cost) * FEE_TIER2_RATE)
    else:
        fee = round0(dec(component_cost) * FEE_TIER3_RATE)
    return component_cost, fee, component_cost + fee


# ---- purity_result_determination ----

def purity_band(lot_product, analyte, reading_ppm):
    """Returns band string, or None when the analyte is unknown for the grade."""
    limits = GRADE_LIMITS_PPM[lot_product]
    if analyte not in limits:
        return None
    limit = limits[analyte]
    reading = round2(reading_ppm)
    if reading <= limit:
        return "OK"
    if reading <= limit * MARGINAL_FACTOR:
        return "MARGINAL"
    return "FAIL"


# ---- blend_conformance_result ----

def blend_component_band(component, actual_pct):
    deviation = round2(abs(dec(actual_pct) - dec(component["target_pct"])))
    tol = dec(component["tolerance_pct"])
    if deviation <= tol:
        return "OK"
    if deviation <= tol * 2:
        return "MARGINAL"
    return "FAIL"


WORST = {"OK": 0, "MARGINAL": 1, "FAIL": 2}


def worst_band(bands):
    worst = "OK"
    for b in bands:
        if WORST[b] > WORST[worst]:
            worst = b
    return worst


# ---- replenishment_order_qty ----

def replenishment_qty(installation):
    current = installation_current_level(installation)
    qty = min(
        dec(installation["capacity_liters"]) - current,
        TRUCK_CAPACITY_LITERS,
        dec(installation["max_order_qty_liters"]),
    )
    return round2(qty)


# ---- credit_hold_evaluation ----

def credit_hold_release_threshold(credit_limit_cents):
    return round0(dec(credit_limit_cents) * HOLD_RELEASE_RATIO)
