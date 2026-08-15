"""Entity serializers — exact field sets per the scaffold entity table."""

from datetime import timedelta

from db import store
from util import iso_dt, iso_d, gal_num, clock_date


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso_dt(rec["created_at"]),
        "updated_at": iso_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_customer(c):
    out = _common(c)
    out.update({
        "name": c["name"],
        "customer_type": c["customer_type"],
        "email": c["email"],
        "status": c["status"],
    })
    return out


def ser_site(s):
    out = _common(s)
    out.update({
        "customer_id": s["customer_id"],
        "name": s["name"],
        "lot_size_sqft": s["lot_size_sqft"],
        "containment_type": s["containment_type"],
        "water_reclaim_required": s["water_reclaim_required"],
        "max_discharge_gal": s["max_discharge_gal"],
        "status": s["status"],
        "suspension_reason": s["suspension_reason"],
    })
    return out


def ser_vehicle(v):
    out = _common(v)
    out.update({
        "customer_id": v["customer_id"],
        "site_id": v["site_id"],
        "plate": v["plate"],
        "vehicle_class": v["vehicle_class"],
    })
    return out


def ser_van(v):
    out = _common(v)
    out.update({
        "name": v["name"],
        "tank_capacity_gal": v["tank_capacity_gal"],
        "reclaim_system": v["reclaim_system"],
        "status": v["status"],
        "water_loaded_gal": gal_num(v["water_loaded_gal"]),
        "water_reserved_gal": gal_num(v["water_reserved_gal"]),
        "water_used_gal": gal_num(v["water_used_gal"]),
    })
    return out


def ser_technician(t):
    out = _common(t)
    out.update({
        "name": t["name"],
        "water_reclaim_certified": t["water_reclaim_certified"],
        "status": t["status"],
    })
    return out


def ser_contract(c):
    out = _common(c)
    out.update({
        "customer_id": c["customer_id"],
        "start_date": c["start_date"],
        "end_date": c["end_date"],
        "monthly_minimum_cents": c["monthly_minimum_cents"],
        "sedan_rate_cents": c["sedan_rate_cents"],
        "suv_pickup_rate_cents": c["suv_pickup_rate_cents"],
        "van_boxtruck_rate_cents": c["van_boxtruck_rate_cents"],
        "heavy_fleet_rate_cents": c["heavy_fleet_rate_cents"],
        "loyalty_credit_pct": c["loyalty_credit_pct"],
        "status": c["status"],
        "early_termination_fee_cents": c["early_termination_fee_cents"],
    })
    return out


def pause_counters(sub):
    """pause_count_365d / paused_days_365d over the trailing 365 days."""
    window_start = clock_date() - timedelta(days=365)
    count = 0
    days = 0
    for p in sub["pauses"]:
        if p["started_at"] >= window_start:
            count += 1
            if p["ended_at"] is None:
                days += (clock_date() - p["started_at"]).days
            else:
                days += p["days"]
    return count, days


def ser_subscription(s):
    out = _common(s)
    count, days = pause_counters(s)
    out.update({
        "customer_id": s["customer_id"],
        "vehicle_id": s["vehicle_id"],
        "cadence": s["cadence"],
        "next_service_date": s["next_service_date"],
        "status": s["status"],
        "pauses": [
            {
                "started_at": iso_d(p["started_at"]),
                "ended_at": iso_d(p["ended_at"]) if p["ended_at"] is not None else None,
                "days": p["days"],
            }
            for p in s["pauses"]
        ],
        "pause_count_365d": count,
        "paused_days_365d": days,
    })
    return out


def ser_order(o):
    out = _common(o)
    out.update({
        "customer_id": o["customer_id"],
        "site_id": o["site_id"],
        "subscription_id": o["subscription_id"],
        "vehicle_ids": list(o["vehicle_ids"]),
        "scheduled_window_start": iso_dt(o["scheduled_window_start"]),
        "scheduled_window_end": iso_dt(o["scheduled_window_end"]),
        "requires_inspection": o["requires_inspection"],
        "status": o["status"],
        "billing_status": o["billing_status"],
        "vehicle_count": len(o["vehicle_ids"]),
        "quote_cents": o["quote_cents"],
        "final_cents": o["final_cents"],
        "vehicles_washed_ids": (list(o["vehicles_washed_ids"])
                                if o["vehicles_washed_ids"] is not None else None),
        "rewash_of_id": o["rewash_of_id"],
        "is_rewash": o["rewash_of_id"] is not None,
        "hold_reason": o["hold_reason"],
        "held_at": iso_dt(o["held_at"]) if o["held_at"] is not None else None,
        "cancel_reason": o["cancel_reason"],
        "completed_at": iso_dt(o["completed_at"]) if o["completed_at"] is not None else None,
    })
    return out


def route_stops(route_id):
    return [s for s in store.stops.values() if s["route_id"] == route_id]


def route_assigned_vehicle_count(route):
    total = 0
    for s in route_stops(route["id"]):
        if s["status"] in ("PLANNED", "ARRIVED", "DONE"):
            order = store.orders.get(s["wash_order_id"])
            if order is not None:
                total += len(order["vehicle_ids"])
    return total


def route_reserved_water(route):
    total = 0
    for s in route_stops(route["id"]):
        if s["status"] in ("PLANNED", "ARRIVED"):
            total += s["reserved_water_gal"]
    return gal_num(total)


def ser_route(r):
    out = _common(r)
    out.update({
        "route_date": r["route_date"],
        "shift_start_at": iso_dt(r["shift_start_at"]),
        "van_id": r["van_id"],
        "lead_technician_id": r["lead_technician_id"],
        "status": r["status"],
        "cancel_reason": r["cancel_reason"],
        "assigned_vehicle_count": route_assigned_vehicle_count(r),
        "reserved_water_gal": route_reserved_water(r),
    })
    return out


def ser_stop(s):
    out = _common(s)
    out.update({
        "route_id": s["route_id"],
        "wash_order_id": s["wash_order_id"],
        "sequence": s["sequence"],
        "planned_start_at": iso_dt(s["planned_start_at"]),
        "planned_end_at": iso_dt(s["planned_end_at"]),
        "status": s["status"],
        "reserved_water_gal": gal_num(s["reserved_water_gal"]),
    })
    return out


def ser_report(r):
    out = _common(r)
    out.update({
        "wash_order_id": r["wash_order_id"],
        "technician_id": r["technician_id"],
        "areas": r["areas"],
        "status": r["status"],
    })
    return out


def ser_audit(a):
    return {
        "id": a["id"],
        "created_at": iso_dt(a["created_at"]),
        "wash_order_id": a["wash_order_id"],
        "auditor_id": a["auditor_id"],
        "exterior_score": a["exterior_score"],
        "wheels_score": a["wheels_score"],
        "glass_score": a["glass_score"],
        "trim_score": a["trim_score"],
        "water_spotting_score": a["water_spotting_score"],
        "total_score": a["total_score"],
        "result": a["result"],
    }


def ser_claim(c):
    out = _common(c)
    out.update({
        "wash_order_id": c["wash_order_id"],
        "customer_id": c["customer_id"],
        "area": c["area"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "description": c["description"],
        "status": c["status"],
        "approved_amount_cents": c["approved_amount_cents"],
        "filed_at": iso_dt(c["filed_at"]),
        "reviewed_by": c["reviewed_by"],
        "paid_by": c["paid_by"],
        "deny_reason": c["deny_reason"],
    })
    return out


def ser_incident(i):
    out = _common(i)
    out.update({
        "site_id": i["site_id"],
        "wash_order_id": i["wash_order_id"],
        "incident_type": i["incident_type"],
        "notes": i["notes"],
        "status": i["status"],
    })
    return out


def ser_invoice(inv):
    out = _common(inv)
    out.update({
        "fleet_contract_id": inv["fleet_contract_id"],
        "period_month": inv["period_month"],
        "variant": inv["variant"],
        "status": inv["status"],
        "line_count": inv["line_count"],
        "charges_cents": inv["charges_cents"],
        "loyalty_credits_cents": inv["loyalty_credits_cents"],
        "minimum_applied": inv["minimum_applied"],
        "billed_cents": inv["billed_cents"],
        "claim_credits_cents": inv["claim_credits_cents"],
        "net_due_cents": inv["net_due_cents"],
    })
    return out


# ----------------------------------------------------------------------------
# Customer ownership derivation (used for Customer-role scoping on reads)
# ----------------------------------------------------------------------------

def customer_of_order(order):
    return order["customer_id"] if order else None


def customer_of_stop(stop):
    order = store.orders.get(stop["wash_order_id"])
    return order["customer_id"] if order else None


def customer_of_report(report):
    order = store.orders.get(report["wash_order_id"])
    return order["customer_id"] if order else None


def customer_of_audit(audit):
    order = store.orders.get(audit["wash_order_id"])
    return order["customer_id"] if order else None


def customer_of_incident(incident):
    site = store.sites.get(incident["site_id"])
    return site["customer_id"] if site else None


def customer_of_invoice(invoice):
    contract = store.contracts.get(invoice["fleet_contract_id"])
    return contract["customer_id"] if contract else None
