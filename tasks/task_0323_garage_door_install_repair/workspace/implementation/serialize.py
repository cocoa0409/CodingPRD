"""Public serialization of entities — the exact field set per entity (SCAFFOLD §1.1).

Computed fields (reserved_qty, available_qty, financing_standing,
active_warranty_count, callback rates, etc.) are recomputed live so reads always
reflect the conserved totals (PRD §2.9, §3.10).
"""
import services.calc as calc


def _base(entity, versioned=True):
    out = {"id": entity["id"], "created_at": entity["created_at"]}
    if versioned:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    return out


def customer(c):
    out = _base(c)
    out.update({
        "full_name": c["full_name"],
        "email": c["email"],
        "service_address": c["service_address"],
        "time_zone": c["time_zone"],
        "financing_standing": calc.financing_standing(c["id"]),
        "active_warranty_count": calc.active_warranty_count(c["id"]),
    })
    return out


def technician(t):
    prov, settled = calc.callback_rates(t["id"])
    out = _base(t)
    out.update({
        "display_name": t["display_name"],
        "skill_level": t["skill_level"],
        "certified_for_install": t["certified_for_install"],
        "status": t["status"],
        "booked_minutes": t["booked_minutes"],
        "jobs_completed_count": calc.jobs_completed_count(t["id"]),
        "callback_rate_provisional": prov,
        "callback_rate_settled": settled,
    })
    return out


def door_model(d):
    out = _base(d, versioned=False)
    out.update({
        "sku": d["sku"],
        "name": d["name"],
        "width_in": d["width_in"],
        "height_in": d["height_in"],
        "list_price_cents": d["list_price_cents"],
        "install_labor_minutes": d["install_labor_minutes"],
        "requires_lift": d["requires_lift"],
    })
    return out


def opener_model(o):
    out = _base(o, versioned=False)
    out.update({
        "sku": o["sku"],
        "name": o["name"],
        "horsepower": o["horsepower"],
        "list_price_cents": o["list_price_cents"],
        "install_labor_minutes": o["install_labor_minutes"],
    })
    return out


def part(p):
    reserved = calc.reserved_qty(p["id"])
    out = _base(p)
    out.update({
        "sku": p["sku"],
        "category": p["category"],
        "unit_price_cents": p["unit_price_cents"],
        "markup_pct": p["markup_pct"],
        "on_hand_qty": p["on_hand_qty"],
        "reserved_qty": reserved,
        "available_qty": max(0, p["on_hand_qty"] - reserved),
    })
    return out


def equipment_unit(e):
    out = _base(e)
    out.update({
        "name": e["name"],
        "concurrent_capacity": e["concurrent_capacity"],
    })
    return out


def quote(q):
    out = _base(q)
    out.update({
        "customer_id": q["customer_id"],
        "quote_type": q["quote_type"],
        "door_model_id": q["door_model_id"],
        "opener_model_id": q["opener_model_id"],
        "status": q["status"],
        "revision": q["revision"],
        "service_call_fee_cents": q["service_call_fee_cents"],
        "estimate_total_cents": q["estimate_total_cents"],
        "expires_at": q["expires_at"],
    })
    return out


def quote_line(l):
    out = _base(l)
    out.update({
        "quote_id": l["quote_id"],
        "item_kind": l["item_kind"],
        "item_ref_id": l["item_ref_id"],
        "qty": l["qty"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
    })
    return out


def job(j):
    out = _base(j)
    out.update({
        "quote_id": j["quote_id"],
        "customer_id": j["customer_id"],
        "technician_id": j["technician_id"],
        "equipment_unit_id": j["equipment_unit_id"],
        "dispatch_status": j["dispatch_status"],
        "billing_status": j["billing_status"],
        "scheduled_start": j["scheduled_start"],
        "scheduled_end": j["scheduled_end"],
        "is_emergency": j["is_emergency"],
        "safety_inspection_passed": j["safety_inspection_passed"],
        "completed_by_user_id": j["completed_by_user_id"],
        "final_total_cents": j["final_total_cents"],
        "emergency_surcharge_cents": j["emergency_surcharge_cents"],
    })
    return out


def part_reservation(r):
    out = _base(r)
    out.update({
        "job_id": r["job_id"],
        "part_id": r["part_id"],
        "qty": r["qty"],
        "status": r["status"],
    })
    return out


def warranty_plan(w):
    out = _base(w)
    out.update({
        "job_id": w["job_id"],
        "customer_id": w["customer_id"],
        "tune_ups_included": w["tune_ups_included"],
        "tune_ups_used": w["tune_ups_used"],
        "status": w["status"],
    })
    return out


def financing_application(f):
    out = _base(f)
    out.update({
        "customer_id": f["customer_id"],
        "quote_id": f["quote_id"],
        "principal_cents": f["principal_cents"],
        "term_months": f["term_months"],
        "status": f["status"],
        "monthly_payment_cents": f["monthly_payment_cents"],
    })
    return out


def callback(c):
    out = _base(c)
    out.update({
        "job_id": c["job_id"],
        "reason": c["reason"],
        "status": c["status"],
        "fault_confirmed": c["fault_confirmed"],
    })
    return out
