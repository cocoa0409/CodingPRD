"""Calculation rules (SCAFFOLD §1.3 / PRD §3.3, §3.6, §3.7, §3.10, §3.12).

All monetary amounts in whole cents; rounding half-up; Decimal for money.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import db
from util import round_half_up_cents, round_half_up_places, ceil_int

LABOR_RATE_CENTS_PER_MIN = 250

AFTER_HOURS_RATE = Decimal("0.25")
OVERNIGHT_RATE = Decimal("0.50")
SURCHARGE_MIN_CENTS = 5000
SURCHARGE_MAX_CENTS = 40000

APR_TIER_0_6 = Decimal("0.00")
APR_TIER_7_12 = Decimal("0.099")
APR_TIER_13_24 = Decimal("0.149")


# ---------------------------------------------------------------------------
# Computed fields for Customer / Technician / Part
# ---------------------------------------------------------------------------
def financing_standing(customer_id):
    """GOOD | BLOCKED — BLOCKED while any FinancingApplication is DEFAULTED."""
    for f in db.financing_applications.values():
        if f["customer_id"] == customer_id and f["status"] == "DEFAULTED":
            return "BLOCKED"
    return "GOOD"


def active_warranty_count(customer_id):
    return sum(
        1 for w in db.warranty_plans.values()
        if w["customer_id"] == customer_id and w["status"] == "ACTIVE"
    )


def reserved_qty(part_id):
    """Sum of qty over HELD PartReservations for this part."""
    return sum(
        r["qty"] for r in db.part_reservations.values()
        if r["part_id"] == part_id and r["status"] == "HELD"
    )


def jobs_completed_count(technician_id):
    return sum(
        1 for j in db.jobs.values()
        if j["technician_id"] == technician_id
        and j["dispatch_status"] in ("COMPLETED", "CLOSED")
    )


def callback_rates(technician_id):
    """(provisional, settled) — see SCAFFOLD technician_callback_rate."""
    denom = jobs_completed_count(technician_id)
    prov_num = 0
    settled_num = 0
    for cb in db.callbacks.values():
        job = db.jobs.get(cb["job_id"])
        if job is None or job["technician_id"] != technician_id:
            continue
        is_resolved = cb["status"] == "RESOLVED"
        fault = cb["fault_confirmed"]
        if (not is_resolved) or (is_resolved and fault):
            prov_num += 1
        if is_resolved and fault:
            settled_num += 1
    if denom == 0:
        return 0, 0
    prov = round_half_up_places(Decimal(prov_num) / Decimal(denom), 4)
    settled = round_half_up_places(Decimal(settled_num) / Decimal(denom), 4)
    return prov, settled


# ---------------------------------------------------------------------------
# quote_estimate_total (PRD §3.3) — MODE (b): round per line, THEN sum.
# ---------------------------------------------------------------------------
def quote_line_raw(line):
    """Raw (un-rounded) line amount by item_kind, as a Decimal of cents."""
    kind = line["item_kind"]
    if kind == "PART":
        part = db.parts[line["item_ref_id"]]
        markup = Decimal(str(part["markup_pct"]))
        return (Decimal(line["qty"]) * Decimal(line["unit_price_cents"])
                * (Decimal(1) + markup))
    if kind == "DOOR":
        quote = db.quotes[line["quote_id"]]
        door = db.door_models[quote["door_model_id"]]
        return Decimal(door["list_price_cents"])
    if kind == "OPENER":
        quote = db.quotes[line["quote_id"]]
        opener = db.opener_models[quote["opener_model_id"]]
        return Decimal(opener["list_price_cents"])
    if kind == "LABOR":
        return Decimal(line["qty"]) * Decimal(LABOR_RATE_CENTS_PER_MIN)
    return Decimal(0)


def compute_line_total(line):
    """Per-line rounded subtotal (round_half_up to whole cents)."""
    return round_half_up_cents(quote_line_raw(line))


def quote_estimate_total(quote):
    """estimate_total_cents = sum(per-line rounded) + service_call_fee (SERVICE_CALL)."""
    lines = [l for l in db.quote_lines.values() if l["quote_id"] == quote["id"]]
    parts_and_goods = sum(round_half_up_cents(quote_line_raw(l)) for l in lines)
    if quote["quote_type"] == "SERVICE_CALL":
        return parts_and_goods + quote["service_call_fee_cents"]
    return parts_and_goods


# ---------------------------------------------------------------------------
# job_final_total + job_emergency_surcharge (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
def consumed_parts_cost(job):
    """Sum over CONSUMED reservations of qty * unit_price * (1+markup),
    rounded half-up per reservation, then summed."""
    total = 0
    for r in db.part_reservations.values():
        if r["job_id"] != job["id"] or r["status"] != "CONSUMED":
            continue
        part = db.parts[r["part_id"]]
        markup = Decimal(str(part["markup_pct"]))
        raw = Decimal(r["qty"]) * Decimal(part["unit_price_cents"]) * (Decimal(1) + markup)
        total += round_half_up_cents(raw)
    return total


def labor_cents(job, quote):
    """Labor component (PRD §3.6)."""
    if quote["quote_type"] == "SERVICE_CALL":
        return quote["service_call_fee_cents"]
    # INSTALL: (door install minutes + opener install minutes if present) * rate
    minutes = 0
    if quote["door_model_id"] is not None:
        door = db.door_models.get(quote["door_model_id"])
        if door is not None:
            minutes += door["install_labor_minutes"]
    if quote["opener_model_id"] is not None:
        opener = db.opener_models.get(quote["opener_model_id"])
        if opener is not None:
            minutes += opener["install_labor_minutes"]
    return minutes * LABOR_RATE_CENTS_PER_MIN


def _band_rate(local_hour_dt):
    """Select band rate from local wall-clock time (PRD §3.7)."""
    # Build a comparable seconds-of-day boundary using exact wall clock.
    t = local_hour_dt
    h, m, s = t.hour, t.minute, t.second
    secs = h * 3600 + m * 60 + s + t.microsecond / 1_000_000
    # BUSINESS: 08:00:00 <= t < 18:00:00 -> 0
    # AFTER_HOURS: 18:00:00 <= t < 22:00:00 -> 0.25 (exactly 18:00:00 is AFTER_HOURS)
    # OVERNIGHT: t >= 22:00:00 or t < 08:00:00 -> 0.50
    if 8 * 3600 <= secs < 18 * 3600:
        return Decimal("0.00")
    if 18 * 3600 <= secs < 22 * 3600:
        return AFTER_HOURS_RATE
    return OVERNIGHT_RATE


def emergency_surcharge(job, quote, base_cents):
    """emergency_surcharge_cents (PRD §3.7)."""
    if not job["is_emergency"]:
        return 0
    # Local wall-clock of scheduled_start in the customer's time_zone.
    customer = db.customers.get(job["customer_id"])
    tz_name = customer["time_zone"] if customer else "America/Los_Angeles"
    start = _parse_iso(job["scheduled_start"])
    if start is None:
        return 0
    try:
        local = start.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = start.astimezone(ZoneInfo("America/Los_Angeles"))
    rate = _band_rate(local)
    raw = Decimal(base_cents) * rate
    if raw <= 0:
        return 0
    rounded = round_half_up_cents(raw)
    # clamp only when raw > 0
    if rounded < SURCHARGE_MIN_CENTS:
        return SURCHARGE_MIN_CENTS
    if rounded > SURCHARGE_MAX_CENTS:
        return SURCHARGE_MAX_CENTS
    return rounded


def job_final_total(job):
    """Returns (final_total_cents, emergency_surcharge_cents)."""
    quote = db.quotes[job["quote_id"]]
    parts_cost = consumed_parts_cost(job)
    labor = labor_cents(job, quote)
    base = parts_cost + labor
    surcharge = emergency_surcharge(job, quote, base)
    final = base + surcharge
    return final, surcharge


def _parse_iso(value):
    if not value:
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# financing_monthly_payment (PRD §3.12)
# ---------------------------------------------------------------------------
def financing_monthly_payment(principal_cents, term_months):
    if term_months <= 6:
        apr = APR_TIER_0_6
    elif term_months <= 12:
        apr = APR_TIER_7_12
    else:
        apr = APR_TIER_13_24
    monthly_rate = apr / Decimal(12)
    if monthly_rate == 0:
        return ceil_int(Decimal(principal_cents) / Decimal(term_months))
    f = (Decimal(1) + monthly_rate) ** term_months
    payment = Decimal(principal_cents) * monthly_rate * f / (f - Decimal(1))
    return round_half_up_cents(payment)
