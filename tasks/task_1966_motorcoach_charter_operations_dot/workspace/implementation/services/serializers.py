"""Serialize entities to API representation."""

import db


def customer_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "company_name": c["company_name"],
        "contact_email": c["contact_email"],
        "contact_phone": c["contact_phone"],
        "billing_address": c["billing_address"],
        "tax_exempt": c["tax_exempt"],
        "credit_status": c["credit_status"],
        "safety_audit_score": c.get("safety_audit_score", 100.0),
        "total_completed_trips": c.get("total_completed_trips", 0),
        "lifetime_revenue_cents": c.get("lifetime_revenue_cents", 0),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def vehicle_view(v: dict) -> dict:
    return {
        "id": v["id"],
        "unit_number": v["unit_number"],
        "make_model": v["make_model"],
        "year": v["year"],
        "seating_capacity": v["seating_capacity"],
        "ada_accessible": v["ada_accessible"],
        "vehicle_class": v["vehicle_class"],
        "status": v["status"],
        "dot_inspection_expiry": v["dot_inspection_expiry"],
        "last_inspection_date": v.get("last_inspection_date"),
        "odometer_miles": v.get("odometer_miles", 0),
        "maintenance_due_miles": v["maintenance_due_miles"],
        "insurance_policy_number": v["insurance_policy_number"],
        "insurance_expiry": v["insurance_expiry"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def driver_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "full_name": d["full_name"],
        "cdl_number": d["cdl_number"],
        "cdl_class": d["cdl_class"],
        "endorsements": d.get("endorsements", []),
        "hire_date": d["hire_date"],
        "status": d["status"],
        "hos_cycle_type": d.get("hos_cycle_type", "CYCLE_70_8"),
        "current_driving_hours_today": d.get("current_driving_hours_today", 0.0),
        "current_on_duty_hours_today": d.get("current_on_duty_hours_today", 0.0),
        "current_cycle_hours": d.get("current_cycle_hours", 0.0),
        "last_rest_start": d.get("last_rest_start"),
        "consecutive_driving_minutes": d.get("consecutive_driving_minutes", 0),
        "safety_score": d.get("safety_score", 100.0),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def quote_view(q: dict) -> dict:
    return {
        "id": q["id"],
        "customer_id": q["customer_id"],
        "trip_date": q["trip_date"],
        "return_date": q["return_date"],
        "origin": q["origin"],
        "destination": q["destination"],
        "passenger_count": q["passenger_count"],
        "estimated_miles": q["estimated_miles"],
        "estimated_hours": q["estimated_hours"],
        "requires_overnight": q.get("requires_overnight", False),
        "requires_relief_driver": q.get("requires_relief_driver", False),
        "ada_required": q.get("ada_required", False),
        "vehicle_class_requested": q.get("vehicle_class_requested", "STANDARD"),
        "status": q["status"],
        "mileage_rate_cents": q.get("mileage_rate_cents"),
        "hourly_rate_cents": q.get("hourly_rate_cents"),
        "overnight_fee_cents": q.get("overnight_fee_cents"),
        "relief_driver_fee_cents": q.get("relief_driver_fee_cents"),
        "subtotal_cents": q.get("subtotal_cents"),
        "tax_cents": q.get("tax_cents"),
        "total_cents": q.get("total_cents"),
        "deposit_cents": q.get("deposit_cents"),
        "quote_expiry": q.get("quote_expiry"),
        "pricing_variant": q.get("pricing_variant"),
        "special_requests": q.get("special_requests", ""),
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def order_view(o: dict) -> dict:
    return {
        "id": o["id"],
        "quote_id": o["quote_id"],
        "customer_id": o["customer_id"],
        "status": o["status"],
        "assigned_vehicle_id": o.get("assigned_vehicle_id"),
        "assigned_driver_id": o.get("assigned_driver_id"),
        "relief_driver_id": o.get("relief_driver_id"),
        "actual_miles": o.get("actual_miles"),
        "actual_hours": o.get("actual_hours"),
        "extra_hours": o.get("extra_hours", 0.0),
        "extra_hours_charge_cents": o.get("extra_hours_charge_cents", 0),
        "fuel_surcharge_cents": o.get("fuel_surcharge_cents", 0),
        "deposit_cents": o.get("deposit_cents"),
        "deposit_paid_cents": o.get("deposit_paid_cents", 0),
        "deposit_paid_at": o.get("deposit_paid_at"),
        "cancellation_fee_cents": o.get("cancellation_fee_cents", 0),
        "refund_cents": o.get("refund_cents", 0),
        "final_subtotal_cents": o.get("final_subtotal_cents"),
        "final_tax_cents": o.get("final_tax_cents"),
        "final_invoice_cents": o.get("final_invoice_cents"),
        "balance_due_cents": o.get("balance_due_cents"),
        "itinerary_changes": o.get("itinerary_changes", []),
        "cancelled_by": o.get("cancelled_by"),
        "cancellation_reason": o.get("cancellation_reason"),
        "completed_at": db.to_iso(o["completed_at"]) if o.get("completed_at") else None,
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def trip_log_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "order_id": t["order_id"],
        "driver_id": t["driver_id"],
        "log_type": t["log_type"],
        "start_time": t["start_time"],
        "end_time": t["end_time"],
        "start_location": t["start_location"],
        "end_location": t["end_location"],
        "miles_driven": t.get("miles_driven", 0),
        "hos_violation": t.get("hos_violation", False),
        "violation_details": t.get("violation_details", ""),
        "created_at": t["created_at"],
    }


def incident_view(i: dict) -> dict:
    return {
        "id": i["id"],
        "order_id": i["order_id"],
        "driver_id": i["driver_id"],
        "vehicle_id": i["vehicle_id"],
        "incident_type": i["incident_type"],
        "severity": i["severity"],
        "description": i["description"],
        "occurred_at": i["occurred_at"],
        "reported_by": i["reported_by"],
        "dot_recordable": i.get("dot_recordable", False),
        "resolution_status": i.get("resolution_status", "OPEN"),
        "resolution_notes": i.get("resolution_notes"),
        "safety_score_impact": i.get("safety_score_impact", 0.0),
        "created_at": i["created_at"],
    }


def maintenance_record_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "vehicle_id": m["vehicle_id"],
        "maintenance_type": m["maintenance_type"],
        "status": m["status"],
        "scheduled_date": m["scheduled_date"],
        "completed_date": m.get("completed_date"),
        "odometer_at_service": m.get("odometer_at_service"),
        "description": m.get("description"),
        "technician": m.get("technician"),
        "cost_cents": m.get("cost_cents"),
        "next_due_miles": m.get("next_due_miles"),
        "dot_inspection_passed": m.get("dot_inspection_passed"),
        "defects_found": m.get("defects_found", []),
        "created_at": m["created_at"],
    }


def breakdown_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "order_id": b["order_id"],
        "vehicle_id": b["vehicle_id"],
        "driver_id": b["driver_id"],
        "location": b["location"],
        "description": b["description"],
        "status": b["status"],
        "replacement_vehicle_id": b.get("replacement_vehicle_id"),
        "replacement_driver_id": b.get("replacement_driver_id"),
        "delay_minutes": b.get("delay_minutes", 0),
        "resolution_notes": b.get("resolution_notes"),
        "customer_compensation_cents": b.get("customer_compensation_cents", 0),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def insurance_certificate_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "order_id": c["order_id"],
        "venue_name": c["venue_name"],
        "venue_address": c["venue_address"],
        "certificate_type": c["certificate_type"],
        "coverage_amount_cents": c["coverage_amount_cents"],
        "status": c["status"],
        "issued_at": c.get("issued_at"),
        "expires_at": c.get("expires_at"),
        "certificate_number": c.get("certificate_number"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def safety_audit_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "customer_id": a["customer_id"],
        "audit_type": a["audit_type"],
        "status": a["status"],
        "requested_date": a["requested_date"],
        "completed_date": a.get("completed_date"),
        "auditor_notes": a.get("auditor_notes"),
        "findings": a.get("findings", []),
        "overall_rating": a.get("overall_rating"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }
