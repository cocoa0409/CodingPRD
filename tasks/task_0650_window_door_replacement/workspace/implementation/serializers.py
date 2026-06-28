"""Serialize internal records to API output. Internal records already use the
public field names, so serialization is mostly identity plus computed fields."""
from db import db
import services


def homeowner_out(h):
    # referral_credit_cents is computed; ensure it is current at read time.
    services.recompute_homeowner_credit(h["id"])
    return {
        "id": h["id"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
        "full_name": h["full_name"],
        "email": h["email"],
        "property_zip": h["property_zip"],
        "agi_band": h["agi_band"],
        "referral_credit_cents": h["referral_credit_cents"],
    }


def project_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "homeowner_id": p["homeowner_id"],
        "jurisdiction_code": p["jurisdiction_code"],
        "status": p["status"],
        "accepted_quote_id": p["accepted_quote_id"],
    }


def consultation_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "project_id": c["project_id"],
        "consultant_id": c["consultant_id"],
        "scheduled_at": c["scheduled_at"],
        "status": c["status"],
        "total_opening_count": c["total_opening_count"],
    }


def opening_out(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "consultation_id": o["consultation_id"],
        "product_type": o["product_type"],
        "width_in": o["width_in"],
        "height_in": o["height_in"],
        "glass_package": o["glass_package"],
        "u_factor": o["u_factor"],
        "energy_qualified": o["energy_qualified"],
        "unit_price_cents": o["unit_price_cents"],
    }


def quote_out(q):
    return {
        "id": q["id"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
        "project_id": q["project_id"],
        "consultation_id": q["consultation_id"],
        "status": q["status"],
        "discount_tier": q["discount_tier"],
        "openings_subtotal_cents": q["openings_subtotal_cents"],
        "estimate_total_cents": q["estimate_total_cents"],
        "provisional_rebate_cents": q["provisional_rebate_cents"],
        "expires_at": q["expires_at"],
    }


def financing_out(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "quote_id": f["quote_id"],
        "requested_amount_cents": f["requested_amount_cents"],
        "term_months": f["term_months"],
        "status": f["status"],
        "approved_apr_bps": f["approved_apr_bps"],
        "monthly_payment_cents": f["monthly_payment_cents"],
    }


def manufacture_out(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "project_id": m["project_id"],
        "quote_id": m["quote_id"],
        "status": m["status"],
        "lead_time_days": m["lead_time_days"],
        "ready_at": m["ready_at"],
    }


def crew_out(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "home_jurisdiction": c["home_jurisdiction"],
        "daily_capacity_openings": c["daily_capacity_openings"],
    }


def install_job_out(j):
    return {
        "id": j["id"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
        "project_id": j["project_id"],
        "crew_id": j["crew_id"],
        "window_start": j["window_start"],
        "window_end": j["window_end"],
        "opening_count": j["opening_count"],
        "status": j["status"],
    }


def permit_out(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "project_id": p["project_id"],
        "status": p["status"],
        "inspection_due_at": p["inspection_due_at"],
    }


def service_ticket_out(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "project_id": t["project_id"],
        "opening_id": t["opening_id"],
        "category": t["category"],
        "status": t["status"],
        "charge_cents": t["charge_cents"],
    }


def referral_out(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "referrer_project_id": r["referrer_project_id"],
        "referred_project_id": r["referred_project_id"],
        "status": r["status"],
        "reward_amount_cents": r["reward_amount_cents"],
    }
