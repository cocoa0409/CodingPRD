"""Entity serializers — convert internal records to API representation."""
from response import iso_format


def serialize_customer(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "status": c["status"],
        "completed_builds_count": c["completed_builds_count"],
        "credit_balance_cents": c["credit_balance_cents"],
        "created_at": iso_format(c["created_at"]),
        "updated_at": iso_format(c["updated_at"]),
        "version": c["version"],
    }


def serialize_staff(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "staff_role": s["staff_role"],
        "active": s["active"],
        "created_at": iso_format(s["created_at"]),
        "updated_at": iso_format(s["updated_at"]),
        "version": s["version"],
    }


def serialize_bay(b):
    return {
        "id": b["id"],
        "bay_name": b["bay_name"],
        "status": b["status"],
        "cleanup_buffer_minutes": b["cleanup_buffer_minutes"],
        "created_at": iso_format(b["created_at"]),
        "updated_at": iso_format(b["updated_at"]),
        "version": b["version"],
    }


def serialize_lesson_package(p):
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "total_credits": p["total_credits"],
        "credits_used": p["credits_used"],
        "price_cents": p["price_cents"],
        "expires_at": iso_format(p["expires_at"]),
        "status": p["status"],
        "created_at": iso_format(p["created_at"]),
        "updated_at": iso_format(p["updated_at"]),
        "version": p["version"],
    }


def serialize_fitting_session(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "bay_id": s["bay_id"],
        "specialist_id": s["specialist_id"],
        "lesson_package_id": s["lesson_package_id"],
        "starts_at": iso_format(s["starts_at"]),
        "ends_at": iso_format(s["ends_at"]),
        "status": s["status"],
        "credit_consumed": s["credit_consumed"],
        "credit_refunded": s["credit_refunded"],
        "created_at": iso_format(s["created_at"]),
        "updated_at": iso_format(s["updated_at"]),
        "version": s["version"],
    }


def serialize_component_item(i):
    return {
        "id": i["id"],
        "sku": i["sku"],
        "component_type": i["component_type"],
        "unit_cost_cents": i["unit_cost_cents"],
        "msrp_cents": i["msrp_cents"],
        "stock_on_hand": i["stock_on_hand"],
        "stock_reserved": i["stock_reserved"],
        "consumed_total": i["consumed_total"],
        "received_total": i["received_total"],
        "created_at": iso_format(i["created_at"]),
        "updated_at": iso_format(i["updated_at"]),
        "version": i["version"],
    }


def serialize_build_spec(s):
    return {
        "id": s["id"],
        "customer_id": s["customer_id"],
        "fitting_session_id": s["fitting_session_id"],
        "head_item_id": s["head_item_id"],
        "shaft_item_id": s["shaft_item_id"],
        "grip_item_id": s["grip_item_id"],
        "length_inches": s["length_inches"],
        "loft_deg": s["loft_deg"],
        "lie_deg": s["lie_deg"],
        "labor_cents": s["labor_cents"],
        "status": s["status"],
        "provisional_quote_cents": s["provisional_quote_cents"],
        "final_price_cents": s["final_price_cents"],
        "payment_method": s["payment_method"],
        "delivered_at": iso_format(s["delivered_at"]) if s["delivered_at"] else None,
        "created_at": iso_format(s["created_at"]),
        "updated_at": iso_format(s["updated_at"]),
        "version": s["version"],
    }


def serialize_component_order(o):
    return {
        "id": o["id"],
        "build_spec_id": o["build_spec_id"],
        "status": o["status"],
        "lines": [dict(line) for line in o["lines"]],
        "required_units": o["required_units"],
        "created_at": iso_format(o["created_at"]),
        "updated_at": iso_format(o["updated_at"]),
        "version": o["version"],
    }


def serialize_repair_ticket(t):
    return {
        "id": t["id"],
        "customer_id": t["customer_id"],
        "club_description": t["club_description"],
        "service_type": t["service_type"],
        "rush": t["rush"],
        "shaft_item_id": t["shaft_item_id"],
        "quoted_total_cents": t["quoted_total_cents"],
        "promised_at": iso_format(t["promised_at"]),
        "deposit_cents": t["deposit_cents"],
        "work_status": t["work_status"],
        "payment_status": t["payment_status"],
        "rework_count": t["rework_count"],
        "picked_up_at": iso_format(t["picked_up_at"]) if t["picked_up_at"] else None,
        "created_at": iso_format(t["created_at"]),
        "updated_at": iso_format(t["updated_at"]),
        "version": t["version"],
    }


def serialize_trade_in_appraisal(a):
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "clubs": [dict(club) for club in a["clubs"]],
        "status": a["status"],
        "offer_basis": a["offer_basis"],
        "offered_value_cents": a["offered_value_cents"],
        "offer_expires_at": iso_format(a["offer_expires_at"]) if a["offer_expires_at"] else None,
        "offered_by_staff_id": a["offered_by_staff_id"],
        "created_at": iso_format(a["created_at"]),
        "updated_at": iso_format(a["updated_at"]),
        "version": a["version"],
    }


def serialize_used_club_listing(l):
    return {
        "id": l["id"],
        "appraisal_id": l["appraisal_id"],
        "appraised_by_staff_id": l["appraised_by_staff_id"],
        "list_price_cents": l["list_price_cents"],
        "status": l["status"],
        "reserved_by_customer_id": l["reserved_by_customer_id"],
        "reserved_until": iso_format(l["reserved_until"]) if l["reserved_until"] else None,
        "created_at": iso_format(l["created_at"]),
        "updated_at": iso_format(l["updated_at"]),
        "version": l["version"],
    }


def serialize_warranty_claim(c):
    return {
        "id": c["id"],
        "customer_id": c["customer_id"],
        "build_spec_id": c["build_spec_id"],
        "repair_ticket_id": c["repair_ticket_id"],
        "description": c["description"],
        "coverage_pct": c["coverage_pct"],
        "covered_estimate_cents": c["covered_estimate_cents"],
        "status": c["status"],
        "appeal_count": c["appeal_count"],
        "denial_reason": c["denial_reason"],
        "created_at": iso_format(c["created_at"]),
        "updated_at": iso_format(c["updated_at"]),
        "version": c["version"],
    }


def serialize_credit_ledger_entry(e):
    return {
        "id": e["id"],
        "customer_id": e["customer_id"],
        "amount_cents": e["amount_cents"],
        "reason": e["reason"],
        "reference_id": e["reference_id"],
        "created_at": iso_format(e["created_at"]),
    }
