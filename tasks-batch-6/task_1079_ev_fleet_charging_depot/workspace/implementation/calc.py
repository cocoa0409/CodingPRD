"""Domain calculations: energy cost, reimbursement, readiness, conflicts, invoice."""
from datetime import timedelta
from decimal import Decimal

import db
from util import D, round_half_up_cents, rate_at, MIN_READY_SOC_PCT, COOLDOWN_BUFFER_MINUTES


# ---------------------------------------------------------------------------
# Session energy cost
# ---------------------------------------------------------------------------
def estimated_cost_cents(vehicle, target_soc_pct, tariff_windows, scheduled_start):
    delta = D(target_soc_pct) - D(vehicle["current_soc_pct"])
    est_energy = delta / D(100) * D(vehicle["battery_capacity_kwh"])
    if est_energy < 0:
        est_energy = D(0)
    rate = rate_at(tariff_windows, scheduled_start.hour)
    return round_half_up_cents(est_energy * D(rate))


def _seconds_by_hour(start_dt, end_dt):
    """Total seconds within [start_dt, end_dt) grouped by UTC hour-of-day (0..23)."""
    buckets = {}
    cur = start_dt
    while cur < end_dt:
        # next hour boundary
        nxt = (cur + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        seg_end = min(nxt, end_dt)
        secs = (seg_end - cur).total_seconds()
        buckets[cur.hour] = buckets.get(cur.hour, 0.0) + secs
        cur = seg_end
    return buckets


def final_cost_cents(final_energy_kwh, tariff_windows, actual_start, actual_end):
    total_s = (actual_end - actual_start).total_seconds()
    if total_s <= 0:
        rate = rate_at(tariff_windows, actual_start.hour)
        return round_half_up_cents(D(final_energy_kwh) * D(rate))
    buckets = _seconds_by_hour(actual_start, actual_end)
    total = Decimal(0)
    energy = D(final_energy_kwh)
    total_sd = D(total_s)
    for hour, secs in buckets.items():
        rate = rate_at(tariff_windows, hour)
        total += energy * (D(secs) / total_sd) * D(rate)
    return round_half_up_cents(total)


def energy_kwh(start_soc, end_soc, battery_capacity_kwh):
    return float((D(end_soc) - D(start_soc)) / D(100) * D(battery_capacity_kwh))


# ---------------------------------------------------------------------------
# Reimbursement
# ---------------------------------------------------------------------------
def reimbursement_cents(kwh, home_tariff_cents_per_kwh):
    return round_half_up_cents(D(kwh) * D(home_tariff_cents_per_kwh))


# ---------------------------------------------------------------------------
# Vehicle readiness
# ---------------------------------------------------------------------------
def readiness(vehicle):
    if vehicle["status"] == "IN_SERVICE" and vehicle["current_soc_pct"] >= MIN_READY_SOC_PCT:
        return "READY"
    return "NOT_READY"


# ---------------------------------------------------------------------------
# Temporal conflict checks
# ---------------------------------------------------------------------------
def charger_conflict(new_start, new_end, existing_sessions):
    """True if new half-open window overlaps any buffered existing window."""
    buf = timedelta(minutes=COOLDOWN_BUFFER_MINUTES)
    for e in existing_sessions:
        es = e["scheduled_start"] - buf
        ee = e["scheduled_end"] + buf
        # half-open overlap: new_start < ee and es < new_end
        if new_start < ee and es < new_end:
            return True
    return False


def vehicle_conflict(new_start, new_end, existing_sessions):
    """True if new closed window overlaps any existing closed window."""
    for e in existing_sessions:
        if new_start <= e["scheduled_end"] and e["scheduled_start"] <= new_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------
def _month_of(dt):
    return dt.strftime("%Y-%m")


def invoice_figures(depot, period_month):
    sessions = [
        s for s in db.charge_sessions.values()
        if s["depot_id"] == depot["id"]
        and s["status"] == "COMPLETED"
        and s.get("actual_end") is not None
        and _month_of(s["actual_end"]) == period_month
    ]
    energy_subtotal = sum(s["final_cost_cents"] for s in sessions)

    peak = 0.0
    for s in sessions:
        t = s["actual_start"]
        conc = 0.0
        for other in sessions:
            if other["actual_start"] <= t < other["actual_end"]:
                conc += other["power_kw"]
        if conc > peak:
            peak = conc

    contracted = depot["contracted_capacity_kw"]
    base = D(depot["demand_rate_cents_per_kw"]) * D(min(peak, contracted))
    overage_amt = peak - contracted
    if overage_amt < 0:
        overage_amt = 0
    overage = D(depot["overage_rate_cents_per_kw"]) * D(overage_amt)
    demand_charge = round_half_up_cents(base + overage)

    total = int(energy_subtotal) + demand_charge
    return {
        "energy_subtotal_cents": int(energy_subtotal),
        "peak_demand_kw": peak,
        "demand_charge_cents": demand_charge,
        "total_cents": total,
    }
