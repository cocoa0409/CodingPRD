"""Calculation rules (SCAFFOLD 1.3 / PRD section 3) and cascade helpers."""
from datetime import timedelta
from decimal import Decimal

from db import DB, touch
from util import D, ceil_int, now, round_half_up

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAFETY_FACTOR = Decimal("1.25")
DEMAND_FACTOR = {
    "CONTINUOUS": Decimal("1.0"),
    "INTERMITTENT": Decimal("0.7"),
    "STANDBY": Decimal("0.35"),
}
VOLTAGE = Decimal("480")
SQRT3 = Decimal("1.732")
SECONDS_PER_DAY = 86400
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 28
LOAD_FACTOR = Decimal("0.75")
SPECIFIC_CONSUMPTION = Decimal("0.28")
METERED_WINDOW_DAYS = 7
FUEL_BUYBACK_CENTS_PER_LITER = 180
SLA_BREACH_CREDIT_CENTS = 25000
JURISDICTION_CAPS = {"CA-SCAQMD": 5.0, "TX-TCEQ": 8.0, "FL-DEP": 12.0}
DEFAULT_CAP = 10.0
TIER2_BAN_CAP_AT_OR_BELOW = 5.0

CONTRACT_TERMINAL = {"CLOSED", "CANCELLED", "EXPIRED"}
VISIT_TERMINAL = {"COMPLETED", "CANCELLED"}
INCIDENT_TERMINAL = {"CHARGED", "WAIVED"}
PERMIT_TERMINAL = {"APPROVED"}
LINE_TERMINAL = {"RELEASED", "RETURNED"}


def jurisdiction_cap(code):
    return JURISDICTION_CAPS.get(code, DEFAULT_CAP)


# ---------------------------------------------------------------------------
# load_sizing (PRD 3.3)
# ---------------------------------------------------------------------------

def load_sizing(load_profile, sizing_method):
    if sizing_method == "NAMEPLATE_SUM":
        total = sum(D(entry["nameplate_kw"]) for entry in load_profile)
    else:  # DIVERSIFIED_DEMAND
        total = sum(
            D(entry["nameplate_kw"]) * DEMAND_FACTOR[entry["load_type"]]
            for entry in load_profile
        )
    return ceil_int(SAFETY_FACTOR * total)


# ---------------------------------------------------------------------------
# accessory_ampacity_requirement (PRD 3.3)
# ---------------------------------------------------------------------------

def required_amps(sized_kw):
    return ceil_int(D(sized_kw) * 1000 / (VOLTAGE * SQRT3))


# ---------------------------------------------------------------------------
# rental_charge_accrual (PRD 3.4 / 3.9) — exact integer cents.
# ---------------------------------------------------------------------------

def accrual_cents(line, start_at, end_at):
    seconds = (end_at - start_at).total_seconds()
    if seconds <= 0:
        duration_days = 0
    else:
        duration_days = max(1, ceil_int(D(seconds) / SECONDS_PER_DAY))
    months = duration_days // DAYS_PER_MONTH
    rem = duration_days - DAYS_PER_MONTH * months
    weeks = rem // DAYS_PER_WEEK
    days = rem - DAYS_PER_WEEK * weeks
    day_block = min(days * line["day_rate_cents"], line["week_rate_cents"]) if days > 0 else 0
    rem_charge = min(weeks * line["week_rate_cents"] + day_block, line["month_rate_cents"])
    time_charge = months * line["month_rate_cents"] + rem_charge
    return time_charge * line["quantity"] + line["demob_fee_cents"]


# ---------------------------------------------------------------------------
# invoice_total (PRD 3.9) — pinned order, round half-up per line first.
# ---------------------------------------------------------------------------

def invoice_total(contract):
    customer = DB.customers[contract["customer_id"]]
    loyalty = D(customer["loyalty_discount_pct"])
    lines_subtotal = 0
    for line in DB.lines.values():
        if line["contract_id"] != contract["id"] or line["final_charge_cents"] is None:
            continue
        discounted = round_half_up(D(line["final_charge_cents"]) * (1 - loyalty), 0)
        lines_subtotal += int(discounted)
    charged = [
        inc
        for inc in DB.incidents.values()
        if inc["contract_id"] == contract["id"] and inc["status"] == "ASSESSED"
    ]
    damage = sum(inc["assessed_charge_cents"] for inc in charged)
    pump_out = sum(
        (t["value"] for t in DB.telemetry.values()
         if t["contract_id"] == contract["id"] and t["event_type"] == "FUEL_PUMP_OUT"),
        Decimal(0),
    )
    fuel_credit = int(round_half_up(pump_out * FUEL_BUYBACK_CENTS_PER_LITER, 0))
    sla_breaches = sum(
        1
        for v in DB.visits.values()
        if v["contract_id"] == contract["id"]
        and v["visit_type"] == "EMERGENCY"
        and v["sla_met"] is False
    )
    sla_credit = SLA_BREACH_CREDIT_CENTS * sla_breaches
    return lines_subtotal + damage - fuel_credit - sla_credit, charged


# ---------------------------------------------------------------------------
# fuel_burn_projection (PRD 3.6)
# ---------------------------------------------------------------------------

def fuel_burn_projection(unit, method):
    current = now()
    window_start = current - timedelta(days=METERED_WINDOW_DAYS)
    window = [
        t for t in DB.telemetry.values()
        if t["equipment_unit_id"] == unit["id"]
        and window_start <= t["recorded_at"] <= current
    ]
    runtime = sum(
        (t["value"] for t in window if t["event_type"] == "RUNTIME"), Decimal(0)
    )
    burn = sum(
        (t["value"] for t in window if t["event_type"] == "FUEL_BURN"), Decimal(0)
    )
    if method == "METERED_AVG" and runtime > 0:
        lph = burn / runtime
    else:
        lph = D(unit["capacity_kw"]) * LOAD_FACTOR * SPECIFIC_CONSUMPTION
    projected_per_day = lph * 24
    site = DB.sites.get(unit["current_site_id"]) if unit["current_site_id"] else None
    tank = site["tank_level_liters"] if site else Decimal(0)
    eta = (tank / lph) if lph > 0 else None
    return {
        "method": method,
        "liters_per_hour": float(round_half_up(lph, 2)),
        "projected_liters_per_day": float(round_half_up(projected_per_day, 2)),
        "next_refuel_eta_hours": (
            float(round_half_up(eta, 2)) if eta is not None else None
        ),
        "telemetry_event_count": len(window),
    }


# ---------------------------------------------------------------------------
# emissions_screening (PRD 3.5)
# ---------------------------------------------------------------------------

def emissions_screening(site):
    units = []
    for line in DB.lines.values():
        if line["line_type"] != "EQUIPMENT" or line["status"] not in ("PENDING", "ON_RENT"):
            continue
        contract = DB.contracts.get(line["contract_id"])
        if contract is None or contract["site_id"] != site["id"]:
            continue
        if contract["status"] not in ("CONFIRMED", "MOBILIZING", "ON_RENT", "SUSPENDED"):
            continue
        unit = DB.units.get(line["equipment_unit_id"])
        if unit is not None:
            units.append(unit)
    cap = jurisdiction_cap(site["jurisdiction_code"])
    if units:
        weighted = sum(D(u["nox_g_per_kwh"]) * u["capacity_kw"] for u in units)
        total_kw = sum(u["capacity_kw"] for u in units)
        aggregate = float(round_half_up(weighted / total_kw, 2))
    else:
        aggregate = 0.0
    return {
        "aggregate_nox_g_per_kwh": aggregate,
        "jurisdiction_cap_g_per_kwh": cap,
        "permit_required": aggregate >= cap,
        "input_unit_count": len(units),
    }


# ---------------------------------------------------------------------------
# standby_sla_evaluation (PRD 3.7)
# ---------------------------------------------------------------------------

def sla_evaluation(visit, customer):
    seconds = (visit["arrived_at"] - visit["requested_at"]).total_seconds()
    visit["response_minutes"] = ceil_int(D(max(seconds, 0)) / 60)
    visit["sla_met"] = visit["response_minutes"] <= customer["sla_response_minutes"]


# ---------------------------------------------------------------------------
# Window overlap helpers (PRD 3.3, 3.7) — half-open intervals.
# ---------------------------------------------------------------------------

def windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def technician_conflict(technician_id, start, end, exclude_visit_id=None):
    """Buffered windows [start-60min, end+60min); cancelled visits ignored."""
    buf_start = start - timedelta(minutes=60)
    buf_end = end + timedelta(minutes=60)
    for v in DB.visits.values():
        if v["id"] == exclude_visit_id or v["status"] == "CANCELLED":
            continue
        if v["assigned_technician_id"] != technician_id:
            continue
        if v["scheduled_start"] is None or v["scheduled_end"] is None:
            continue
        o_start = v["scheduled_start"] - timedelta(minutes=60)
        o_end = v["scheduled_end"] + timedelta(minutes=60)
        if windows_overlap(buf_start, buf_end, o_start, o_end):
            return True
    return False


# ---------------------------------------------------------------------------
# Cascade helpers (PRD 2.9): each hop is a real mutation (version bump).
# ---------------------------------------------------------------------------

def release_contract_reservations(contract, ts):
    """Compensating release: PENDING lines -> RELEASED; units RESERVED for this
    contract (and no other active reservation) -> AVAILABLE."""
    affected_units = []
    for line in DB.lines.values():
        if line["contract_id"] != contract["id"] or line["status"] != "PENDING":
            continue
        line["status"] = "RELEASED"
        touch(line, ts)
        if line["line_type"] == "EQUIPMENT":
            affected_units.append(line["equipment_unit_id"])
    for unit_id in affected_units:
        unit = DB.units.get(unit_id)
        if unit is None or unit["status"] != "RESERVED":
            continue
        still_reserved = any(
            l["line_type"] == "EQUIPMENT"
            and l["equipment_unit_id"] == unit_id
            and l["status"] in ("PENDING", "ON_RENT")
            for l in DB.lines.values()
        )
        if not still_reserved:
            unit["status"] = "AVAILABLE"
            touch(unit, ts)


def finalize_line(line, ts):
    """ON_RENT -> OFF_HIRED: final accrual to now plus demob; unit -> OFF_RENT."""
    contract = DB.contracts[line["contract_id"]]
    line["final_charge_cents"] = accrual_cents(line, contract["start_date"], ts)
    line["offhired_at"] = ts
    line["status"] = "OFF_HIRED"
    touch(line, ts)
    if line["line_type"] == "EQUIPMENT":
        unit = DB.units.get(line["equipment_unit_id"])
        if unit is not None and unit["status"] == "DEPLOYED":
            unit["status"] = "OFF_RENT"
            unit["current_site_id"] = None
            touch(unit, ts)


def quote_expiry_sweep(ts):
    """Clock advance: QUOTED contracts past quoted_at + 7 days -> EXPIRED."""
    for contract in DB.contracts.values():
        if contract["status"] != "QUOTED" or contract["quoted_at"] is None:
            continue
        if ts > contract["quoted_at"] + timedelta(days=7):
            contract["status"] = "EXPIRED"
            touch(contract, ts)
            release_contract_reservations(contract, ts)
