"""Public serialization views. Strips internal bookkeeping fields (_seq, etc.)."""

# Internal fields never exposed in API output.
_INTERNAL = {"_seq"}


def _clean(entity):
    return {k: v for k, v in entity.items() if k not in _INTERNAL}


def customer_view(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "credit_limit_cents": c["credit_limit_cents"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def technician_view(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "ladder_cert_max_stories": t["ladder_cert_max_stories"],
        "insurance_status": t["insurance_status"],
        "scheduled_minutes": t["scheduled_minutes"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def route_view(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "travel_buffer_minutes": r["travel_buffer_minutes"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def property_view(p):
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "route_id": p["route_id"],
        "address": p["address"],
        "stories": p["stories"],
        "roof_sqft": p["roof_sqft"],
        "siding_sqft": p["siding_sqft"],
        "concrete_sqft": p["concrete_sqft"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def quote_view(q):
    return {
        "id": q["id"],
        "property_id": q["property_id"],
        "soiling_level": q["soiling_level"],
        "subtotal_cents": q["subtotal_cents"],
        "travel_surcharge_cents": q["travel_surcharge_cents"],
        "total_cents": q["total_cents"],
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def line_item_view(li):
    return {
        "id": li["id"],
        "quote_id": li["quote_id"],
        "surface_type": li["surface_type"],
        "service_type": li["service_type"],
        "measured_sqft": li["measured_sqft"],
        "chemical_dose_oz": li["chemical_dose_oz"],
        "line_total_cents": li["line_total_cents"],
        "created_at": li["created_at"],
    }


def plan_view(p):
    return {
        "id": p["id"],
        "property_id": p["property_id"],
        "source_quote_id": p["source_quote_id"],
        "cadence_days": p["cadence_days"],
        "next_due_utc": p["next_due_utc"],
        "visits_generated_count": p["visits_generated_count"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def visit_view(v):
    return {
        "id": v["id"],
        "property_id": v["property_id"],
        "quote_id": v["quote_id"],
        "plan_id": v["plan_id"],
        "route_id": v["route_id"],
        "scheduled_date": v["scheduled_date"],
        "duration_minutes": v["duration_minutes"],
        "provisional_cost_cents": v["provisional_cost_cents"],
        "final_cost_cents": v["final_cost_cents"],
        "reclean_of_visit_id": v["reclean_of_visit_id"],
        "billing_status": v["billing_status"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def assignment_view(a):
    return {
        "id": a["id"],
        "visit_id": a["visit_id"],
        "technician_id": a["technician_id"],
        "window_start_utc": a["window_start_utc"],
        "duration_minutes": a["duration_minutes"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def weather_window_view(w):
    return {
        "id": w["id"],
        "route_id": w["route_id"],
        "window_start_utc": w["window_start_utc"],
        "window_end_utc": w["window_end_utc"],
        "wind_mph": w["wind_mph"],
        "condition": w["condition"],
        "precip_flag": w["precip_flag"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def photo_set_view(p):
    return {
        "id": p["id"],
        "visit_id": p["visit_id"],
        "phase": p["phase"],
        "photo_url": p["photo_url"],
        "created_at": p["created_at"],
    }


def invoice_view(i):
    return {
        "id": i["id"],
        "visit_id": i["visit_id"],
        "customer_id": i["customer_id"],
        "amount_due_cents": i["amount_due_cents"],
        "loyalty_discount_cents": i["loyalty_discount_cents"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def claim_view(c):
    return {
        "id": c["id"],
        "visit_id": c["visit_id"],
        "reason": c["reason"],
        "reclean_visit_id": c["reclean_visit_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
