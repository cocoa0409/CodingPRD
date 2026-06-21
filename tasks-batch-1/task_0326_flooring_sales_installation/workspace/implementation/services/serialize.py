"""Public serialization of stored records.

We store records as plain dicts already shaped like the public resource, so the
serializers mostly return copies. Kept explicit so field sets stay PRD-faithful.
"""


def product_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "material_cost_per_sqft_cents": p["material_cost_per_sqft_cents"],
        "labor_rate_per_sqft_cents": p["labor_rate_per_sqft_cents"],
        "requires_underlayment": p["requires_underlayment"],
        "underlayment_cost_per_sqft_cents": p["underlayment_cost_per_sqft_cents"],
        "lead_time_days": p["lead_time_days"],
        "warranty_years": p["warranty_years"],
        "status": p["status"],
    }


def job_view(j):
    return {
        "id": j["id"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
        "customer_id": j["customer_id"],
        "sales_rep_id": j["sales_rep_id"],
        "product_id": j["product_id"],
        "declared_sqft": j["declared_sqft"],
        "measured_sqft": j["measured_sqft"],
        "tear_out_sqft": j["tear_out_sqft"],
        "room_count": j["room_count"],
        "waste_factor_pct": j["waste_factor_pct"],
        "status": j["status"],
        "warranty_risk_score": j["warranty_risk_score"],
    }


def estimate_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "job_id": e["job_id"],
        "variant": e["variant"],
        "billable_sqft": e["billable_sqft"],
        "material_cost_cents": e["material_cost_cents"],
        "underlayment_cost_cents": e["underlayment_cost_cents"],
        "labor_cost_cents": e["labor_cost_cents"],
        "total_cents": e["total_cents"],
        "status": e["status"],
        "valid_until": e["valid_until"],
        "expected_job_version": e["expected_job_version"],
    }


def material_order_view(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "job_id": m["job_id"],
        "product_id": m["product_id"],
        "order_sqft": m["order_sqft"],
        "lead_time_days": m["lead_time_days"],
        "expected_ready_date": m["expected_ready_date"],
        "status": m["status"],
        "backorder_count": m["backorder_count"],
    }


def crew_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "skill_categories": list(c["skill_categories"]),
        "daily_sqft_capacity": c["daily_sqft_capacity"],
        "buffer_minutes": c["buffer_minutes"],
        "status": c["status"],
    }


def slot_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "job_id": s["job_id"],
        "crew_id": s["crew_id"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "scheduled_sqft": s["scheduled_sqft"],
        "status": s["status"],
    }


def claim_view(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "job_id": w["job_id"],
        "filed_at": w["filed_at"],
        "defect_description": w["defect_description"],
        "status": w["status"],
        "resolution_note": w["resolution_note"],
    }


def customer_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "full_name": c["full_name"],
        "address": c["address"],
        "email": c["email"],
    }


def sales_rep_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "name": r["name"],
    }
