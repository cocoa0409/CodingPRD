"""Business calculations (scaffold 1.3) and shared side-effect helpers."""

from decimal import Decimal

from db import store
from util import dec, rhu, rhu_int, now, touch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGULAR_HOURS_PER_ASSIGNMENT = Decimal("8.0")

TIER1_THRESHOLD_CENTS = 500000
TIER1_PCT = Decimal("0.03")
TIER2_THRESHOLD_CENTS = 2000000
TIER2_PCT = Decimal("0.07")
ENV_FEE_PCT = Decimal("0.02")

GRACE_MINUTES = {
    "CUSTOMER_DELAY": 30,
    "WEATHER": 60,
    "REGULATORY_HOLD": 0,
    "SAFETY_STOP": 0,
    "CONTRACTOR_FAULT": 0,
}
DAILY_CAP_MINUTES = 480
BILLING_BLOCK_MINUTES = 15

EXCEPTION_THRESHOLD_PCT = Decimal("10.00")
MIN_CAPTURE_RATIO = Decimal("0.9500")

DISCOUNTABLE_KINDS = {"VACUUM", "HYDRO", "LABOR_REG", "LABOR_OT", "EQUIPMENT", "STANDBY"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def job_assignments(job_id):
    return [a for a in store.assignments.values() if a["job_id"] == job_id]


def job_jhas(job_id):
    return [j for j in store.jhas.values() if j["job_id"] == job_id]


def job_permits(job_id):
    return [p for p in store.permits.values() if p["job_id"] == job_id]


def job_manifests(job_id):
    return [m for m in store.manifests.values() if m["job_id"] == job_id]


def job_downtime(job_id):
    return [d for d in store.downtime_events.values() if d["job_id"] == job_id]


def job_containment(job_id):
    return [c for c in store.containment_records.values() if c["job_id"] == job_id]


def job_incidents(job_id):
    return [i for i in store.incidents.values() if i["job_id"] == job_id]


def approved_jha(job_id):
    """At most one APPROVED revision exists per job at any time."""
    for j in job_jhas(job_id):
        if j["status"] == "APPROVED":
            return j
    return None


def pinned_schedule(job):
    return store.rate_schedules.get(job["pinned_rate_schedule_id"])


# ---------------------------------------------------------------------------
# Derived aggregates (immediate consistency, PRD section 2.4 / 2.9)
# ---------------------------------------------------------------------------

def recompute_standby_accrual(job):
    """job_standby_accrual: sum billed amounts over CLOSED/BILLED events."""
    total = sum(
        d["billed_amount_cents"] or 0
        for d in job_downtime(job["id"])
        if d["status"] in ("CLOSED", "BILLED")
    )
    job["standby_accrued_cents"] = total


def recompute_facility(facility):
    """facility_reservation_sync: reserved tons over ISSUED manifests; posture."""
    reserved = Decimal("0")
    for m in store.manifests.values():
        if m["status"] != "ISSUED" or m.get("estimated_tons") is None:
            continue
        profile = store.waste_profiles.get(m["waste_profile_id"])
        if profile is not None and profile["facility_id"] == facility["id"]:
            reserved += dec(m["estimated_tons"])
    facility["reserved_tons"] = rhu(reserved, 2)
    facility["posture"] = (
        "FULL" if facility["reserved_tons"] >= dec(facility["total_capacity_tons"])
        else "AVAILABLE"
    )
    touch(facility)


# ---------------------------------------------------------------------------
# downtime_billing
# ---------------------------------------------------------------------------

def compute_downtime_closure(event, ended_at):
    """Populate duration/grace/billable/blocks/amount on a closing event."""
    job = store.jobs[event["job_id"]]
    schedule = pinned_schedule(job)
    started = event["started_at"]
    duration = int((ended_at - started).total_seconds() // 60)
    if duration < 0:
        duration = 0
    cause = event["cause"]
    grace = GRACE_MINUTES[cause]
    if cause == "CONTRACTOR_FAULT":
        billable = 0
    else:
        raw = max(0, duration - grace)
        accrued = sum(
            other["billable_minutes"] or 0
            for other in job_downtime(event["job_id"])
            if other["id"] != event["id"]
            and other["status"] in ("CLOSED", "BILLED")
            and other["closure_day"] == event["closure_day"]
        )
        billable = min(raw, max(0, DAILY_CAP_MINUTES - accrued))
    blocks = (billable + BILLING_BLOCK_MINUTES - 1) // BILLING_BLOCK_MINUTES
    amount = rhu_int(Decimal(blocks) * dec(schedule["standby_rate_cents_per_hour"]) / 4)

    event["ended_at"] = ended_at
    event["duration_minutes"] = duration
    event["grace_minutes_applied"] = grace
    event["billable_minutes"] = billable
    event["billed_blocks"] = blocks
    event["billed_amount_cents"] = amount


# ---------------------------------------------------------------------------
# Invoice construction: job_invoice_amount + invoice_line_rounding +
# invoice_volume_discount
# ---------------------------------------------------------------------------

def _line(line_id, kind, description, quantity, unit, rate_cents, amount_cents,
          discountable, origin):
    return {
        "line_id": line_id,
        "kind": kind,
        "description": description,
        "quantity": quantity,
        "unit": unit,
        "rate_cents": rate_cents,
        "amount_cents": amount_cents,
        "discountable": discountable,
        "voided": False,
        "origin": origin,
    }


def build_invoice_lines(job):
    """Return the ordered line list for a fresh invoice generation."""
    schedule = pinned_schedule(job)
    lines = []

    if job["pricing_mode"] == "UNIT_RATE":
        work_total = 0
        if job["job_type"] in ("VACUUM", "COMBINED"):
            qty = job["gallons_removed"]
            rate = schedule["vacuum_per_gallon_cents"]
            amount = qty * rate  # integer quantities and rates: exact
            work_total += amount
            lines.append(("VACUUM", "Vacuum waste removal", qty, "gallon",
                          rate, amount, True, "SYSTEM"))
        if job["job_type"] in ("HYDROBLAST", "COMBINED"):
            qty = job["feet_cleaned"]
            rate = schedule["hydroblast_per_foot_cents"]
            amount = qty * rate
            work_total += amount
            lines.append(("HYDRO", "Hydroblasting", qty, "foot",
                          rate, amount, True, "SYSTEM"))
        minimum = schedule["minimum_invoice_cents"]
        if minimum and work_total < minimum:
            lines.append(("ADJUSTMENT", "Minimum invoice charge adjustment",
                          1, "each", minimum - work_total, minimum - work_total,
                          False, "AUTO_MINIMUM"))
    else:  # TIME_AND_MATERIALS
        labor_rate = schedule["labor_rate_cents_per_hour"]
        equip_rate = schedule["equipment_rate_cents_per_hour"]
        mult = dec(schedule["overtime_multiplier"])
        crew = [a for a in job_assignments(job["id"])
                if a["status"] in ("CONFIRMED", "RELEASED")]
        crew.sort(key=lambda a: a["created_at"])
        for a in crew:
            hours = dec(a["window_hours"])
            if a["resource_kind"] == "OPERATOR":
                reg = min(REGULAR_HOURS_PER_ASSIGNMENT, hours)
                ot = max(Decimal("0"), hours - REGULAR_HOURS_PER_ASSIGNMENT)
                reg_amount = rhu_int(reg * labor_rate)
                lines.append(("LABOR_REG", "Labor (regular hours)", float(reg),
                              "hour", labor_rate, reg_amount, True, "SYSTEM"))
                if ot > 0:
                    ot_amount = rhu_int(ot * labor_rate * mult)
                    lines.append(("LABOR_OT", "Labor (overtime hours)", float(ot),
                                  "hour", labor_rate, ot_amount, True, "SYSTEM"))
            else:
                amount = rhu_int(hours * equip_rate)
                lines.append(("EQUIPMENT", "Equipment", float(hours), "hour",
                              equip_rate, amount, True, "SYSTEM"))

    # Shared trailing groups, both variants.
    events = [d for d in job_downtime(job["id"])
              if d["status"] in ("CLOSED", "BILLED") and (d["billable_minutes"] or 0) > 0]
    events.sort(key=lambda d: d["created_at"])
    standby_block_rate = None
    if job["pricing_mode"] is not None:
        schedule = pinned_schedule(job)
        standby_block_rate = rhu_int(dec(schedule["standby_rate_cents_per_hour"]) / 4)
    for d in events:
        lines.append(("STANDBY", "Standby / downtime", d["billed_blocks"], "block",
                      standby_block_rate, d["billed_amount_cents"], True, "SYSTEM"))

    manifests = [m for m in job_manifests(job["id"]) if m["status"] == "RECONCILED"]
    manifests.sort(key=lambda m: m["created_at"])
    for m in manifests:
        profile = store.waste_profiles.get(m["waste_profile_id"])
        rate = profile["disposal_rate_per_ton_cents"] if profile else 0
        lines.append(("DISPOSAL", "Waste disposal", float(dec(m["billed_tons"])),
                      "ton", rate, m["disposal_charge_cents"], False, "SYSTEM"))

    out = []
    for idx, (kind, desc, qty, unit, rate, amount, discountable, origin) in enumerate(lines):
        out.append(_line("L%d" % (idx + 1), kind, desc, qty, unit, rate,
                         amount, discountable, origin))
    return out


def recompute_invoice_totals(invoice):
    """invoice_volume_discount: pinned evaluation order on non-voided lines."""
    active = [ln for ln in invoice["lines"] if not ln["voided"]]
    subtotal = sum(ln["amount_cents"] for ln in active)
    discountable_subtotal = sum(ln["amount_cents"] for ln in active if ln["discountable"])
    if discountable_subtotal >= TIER2_THRESHOLD_CENTS:
        tier = TIER2_PCT
    elif discountable_subtotal >= TIER1_THRESHOLD_CENTS:
        tier = TIER1_PCT
    else:
        tier = Decimal("0")
    discount = rhu_int(Decimal(discountable_subtotal) * tier)
    env_fee = rhu_int(Decimal(subtotal - discount) * ENV_FEE_PCT)
    invoice["subtotal_cents"] = subtotal
    invoice["discount_cents"] = discount
    invoice["environmental_fee_cents"] = env_fee
    invoice["total_cents"] = subtotal - discount + env_fee
