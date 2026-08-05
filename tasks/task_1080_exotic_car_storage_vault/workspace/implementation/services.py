"""Serializers, calculations, and cascading business logic."""
from decimal import Decimal

import core
from core import (
    db, iso, rhu, touch, common_out, now_clock,
    TIER_DISCOUNT_PCT, CLIMATE_SURCHARGE_CENTS, SHOWCASE_SURCHARGE_CENTS,
    MAX_DISCOUNT_CENTS, PRORATION_DAYS_IN_MONTH, LABOR_RATE_CENTS,
    SERVICE_BASE_CENTS, TAX_RATE, DELIVERY_FLAT_CENTS, BATTERY_MIN_VOLTAGE,
    TIER_RANK,
)

TERMINAL_AGREEMENT = {"CLOSED", "CANCELLED"}


def sort_created_key(r):
    return (r["created_at"], r["_seq"])


# ===========================================================================
# Calculations
# ===========================================================================
def tier_discount_pct(tier):
    return float(TIER_DISCOUNT_PCT[tier])


def storage_monthly_fee(unit, member):
    base = unit["monthly_rate_cents"]
    surcharge = 0
    if unit["unit_class"] == "CLIMATE":
        surcharge = CLIMATE_SURCHARGE_CENTS
    elif unit["unit_class"] == "SHOWCASE":
        surcharge = SHOWCASE_SURCHARGE_CENTS
    gross = base + surcharge
    pct = Decimal(TIER_DISCOUNT_PCT[member["membership_tier"]])
    raw_discount = Decimal(gross) * pct
    discount = min(raw_discount, Decimal(MAX_DISCOUNT_CENTS))
    return rhu(Decimal(gross) - discount)


def storage_proration(agreement, mode):
    monthly = agreement["monthly_rate_cents"]
    if mode == "FULL_MONTH":
        return monthly
    days = agreement["days_stored"] or 0
    capped = min(days, PRORATION_DAYS_IN_MONTH)
    return rhu(Decimal(monthly) * Decimal(capped) / Decimal(PRORATION_DAYS_IN_MONTH))


def service_estimate(order):
    base = SERVICE_BASE_CENTS[order["service_type"]]
    hours = Decimal(str(order["estimated_labor_hours"]))
    return rhu(Decimal(base) + hours * Decimal(LABOR_RATE_CENTS))


def service_final(order):
    base = SERVICE_BASE_CENTS[order["service_type"]]
    hours = Decimal(str(order["actual_labor_hours"]))
    parts = Decimal(order["parts_cents"] or 0)
    return rhu(Decimal(base) + hours * Decimal(LABOR_RATE_CENTS) + parts)


# ===========================================================================
# Member money aggregates (computed on read)
# ===========================================================================
def member_charged(member_id):
    return sum(inv["total_cents"] for inv in db.invoices.values()
               if inv["member_id"] == member_id and inv["status"] in ("ISSUED", "PAID"))


def member_paid(member_id):
    return sum(p["amount_cents"] for p in db.payments if p["member_id"] == member_id)


def member_held(member_id):
    total = 0
    for so in db.service_orders.values():
        if so["status"] in ("APPROVED", "IN_PROGRESS", "ON_HOLD"):
            agr = db.agreements.get(so["agreement_id"])
            if agr and agr["member_id"] == member_id:
                total += so["estimated_cost_cents"] or 0
    return total


# ===========================================================================
# Facility unit counts
# ===========================================================================
def facility_counts(facility_id):
    counts = {"AVAILABLE": 0, "RESERVED": 0, "OCCUPIED": 0, "OUT_OF_SERVICE": 0}
    for u in db.units.values():
        if u["facility_id"] == facility_id:
            counts[u["status"]] += 1
    return counts


# ===========================================================================
# Vehicle insurance status (computed on read)
# ===========================================================================
def vehicle_insurance_status(vehicle_id):
    clock = now_clock()
    has_expired_or_revoked = False
    for coi in db.cois.values():
        if coi["vehicle_id"] != vehicle_id:
            continue
        if coi["status"] == "ACTIVE" and coi["effective_at"] <= clock < coi["expiry_at"]:
            return "ACTIVE"
        if coi["status"] in ("EXPIRED", "REVOKED"):
            has_expired_or_revoked = True
    return "LAPSED" if has_expired_or_revoked else "NONE"


# ===========================================================================
# Serializers
# ===========================================================================
def ser_facility(f):
    c = facility_counts(f["id"])
    out = common_out(f)
    out.update({
        "name": f["name"],
        "total_units": f["total_units"],
        "units_available": c["AVAILABLE"],
        "units_reserved": c["RESERVED"],
        "units_occupied": c["OCCUPIED"],
        "units_out_of_service": c["OUT_OF_SERVICE"],
    })
    return out


def ser_unit(u):
    out = common_out(u)
    out.update({
        "facility_id": u["facility_id"],
        "unit_code": u["unit_code"],
        "unit_class": u["unit_class"],
        "climate_controlled": u["unit_class"] in ("CLIMATE", "SHOWCASE"),
        "monthly_rate_cents": u["monthly_rate_cents"],
        "status": u["status"],
    })
    return out


def ser_member(m):
    charged = member_charged(m["id"])
    paid = member_paid(m["id"])
    held = member_held(m["id"])
    out = common_out(m)
    out.update({
        "full_name": m["full_name"],
        "email": m["email"],
        "membership_tier": m["membership_tier"],
        "tier_discount_pct": tier_discount_pct(m["membership_tier"]),
        "billing_status": m["billing_status"],
        "charged_cents": charged,
        "paid_cents": paid,
        "held_cents": held,
        "account_balance_cents": charged - paid,
    })
    return out


def ser_vehicle(v):
    out = common_out(v)
    out.update({
        "member_id": v["member_id"],
        "make": v["make"],
        "model": v["model"],
        "model_year": v["model_year"],
        "vin": v["vin"],
        "fuel_type": v["fuel_type"],
        "declared_value_cents": v["declared_value_cents"],
        "condition_status": v["condition_status"],
        "insurance_status": vehicle_insurance_status(v["id"]),
    })
    return out


def ser_coi(c):
    out = common_out(c)
    out.update({
        "vehicle_id": c["vehicle_id"],
        "policy_number": c["policy_number"],
        "carrier": c["carrier"],
        "coverage_amount_cents": c["coverage_amount_cents"],
        "effective_at": iso(c["effective_at"]),
        "expiry_at": iso(c["expiry_at"]),
        "status": c["status"],
    })
    return out


def ser_agreement(a):
    out = common_out(a)
    out.update({
        "member_id": a["member_id"],
        "vehicle_id": a["vehicle_id"],
        "unit_id": a["unit_id"],
        "move_in_at": iso(a["move_in_at"]),
        "planned_move_out_at": iso(a["planned_move_out_at"]),
        "actual_move_out_at": iso(a["actual_move_out_at"]),
        "monthly_rate_cents": a["monthly_rate_cents"],
        "days_stored": a["days_stored"],
        "status": a["status"],
    })
    return out


def ser_monitoring(s):
    out = common_out(s)
    out.update({
        "agreement_id": s["agreement_id"],
        "monitor_type": s["monitor_type"],
        "monthly_fee_cents": s["monthly_fee_cents"],
        "status": s["status"],
        "last_battery_voltage": s["last_battery_voltage"],
        "low_battery_alert": (s["last_battery_voltage"] is not None
                              and s["last_battery_voltage"] < BATTERY_MIN_VOLTAGE),
    })
    return out


def ser_service_order(o):
    out = common_out(o)
    out.update({
        "agreement_id": o["agreement_id"],
        "service_type": o["service_type"],
        "estimated_labor_hours": o["estimated_labor_hours"],
        "actual_labor_hours": o["actual_labor_hours"],
        "parts_cents": o["parts_cents"],
        "estimated_cost_cents": o["estimated_cost_cents"],
        "final_cost_cents": o["final_cost_cents"],
        "scheduled_at": iso(o["scheduled_at"]),
        "status": o["status"],
    })
    return out


def ser_transporter(t):
    out = common_out(t)
    out.update({
        "name": t["name"],
        "buffer_minutes": t["buffer_minutes"],
        "status": t["status"],
    })
    return out


def ser_delivery(d):
    out = common_out(d)
    out.update({
        "vehicle_id": d["vehicle_id"],
        "transporter_id": d["transporter_id"],
        "event_name": d["event_name"],
        "pickup_at": iso(d["pickup_at"]),
        "dropoff_at": iso(d["dropoff_at"]),
        "status": d["status"],
    })
    return out


def ser_waitlist(w):
    out = common_out(w)
    out.update({
        "member_id": w["member_id"],
        "desired_unit_class": w["desired_unit_class"],
        "facility_id": w["facility_id"],
        "status": w["status"],
        "offered_unit_id": w["offered_unit_id"],
        "offer_expires_at": iso(w["offer_expires_at"]),
    })
    return out


def ser_inspection(i):
    out = common_out(i)
    out.update({
        "vehicle_id": i["vehicle_id"],
        "inspection_type": i["inspection_type"],
        "status": i["status"],
        "damage_noted": i["damage_noted"],
        "findings": i["findings"],
    })
    return out


def ser_invoice(inv):
    out = common_out(inv)
    out.update({
        "member_id": inv["member_id"],
        "agreement_id": inv["agreement_id"],
        "period_start_at": iso(inv["period_start_at"]),
        "period_end_at": iso(inv["period_end_at"]),
        "proration_mode": inv["proration_mode"],
        "line_items": [dict(li) for li in inv["line_items"]],
        "subtotal_cents": inv["subtotal_cents"],
        "tax_cents": inv["tax_cents"],
        "total_cents": inv["total_cents"],
        "due_at": iso(inv["due_at"]),
        "status": inv["status"],
    })
    return out


# ===========================================================================
# Cascade / state helpers
# ===========================================================================
def run_waitlist_promotion(unit):
    """If unit is AVAILABLE, offer it to the top-ranked eligible WAITING entry."""
    if unit["status"] != "AVAILABLE":
        return
    candidates = [
        w for w in db.waitlist.values()
        if w["status"] == "WAITING"
        and w["facility_id"] == unit["facility_id"]
        and w["desired_unit_class"] == unit["unit_class"]
    ]
    if not candidates:
        return

    def rank_key(w):
        member = db.members.get(w["member_id"])
        tier = member["membership_tier"] if member else "BRONZE"
        return (-TIER_RANK[tier], w["created_at"], w["_seq"])

    candidates.sort(key=rank_key)
    entry = candidates[0]
    # Offer the unit.
    entry["status"] = "OFFERED"
    entry["offered_unit_id"] = unit["id"]
    entry["offer_expires_at"] = now_clock() + _hours(core.OFFER_TTL_HOURS)
    touch(entry)
    unit["status"] = "RESERVED"
    touch(unit)


def _hours(h):
    from datetime import timedelta
    return timedelta(hours=h)


def release_unit_to_available(unit):
    """OCCUPIED -> AVAILABLE, bump version, then run waitlist promotion."""
    unit["status"] = "AVAILABLE"
    touch(unit)
    run_waitlist_promotion(unit)


def cancel_scheduled_deliveries_for_vehicle(vehicle_id):
    for job in db.delivery_jobs.values():
        if job["vehicle_id"] == vehicle_id and job["status"] == "SCHEDULED":
            job["status"] = "CANCELLED"
            touch(job)
