"""Entity -> JSON dict serializers (exact scaffold field sets)."""

import calc
from db import fmt_dt


def carrier(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "usdot_number": c["usdot_number"],
        "fleet_size_declared": c["fleet_size_declared"],
        "verified_fleet_size": c["verified_fleet_size"],
        "hazmat_categories": list(c["hazmat_categories"]),
        "accepts_dangerous_placard_substitution": c["accepts_dangerous_placard_substitution"],
        "registration_status": c["registration_status"],
        "registration_tier": c["registration_tier"],
        "registration_expires_at": fmt_dt(c["registration_expires_at"]),
        "security_plan_required": calc.carrier_security_plan_required(c),
        "outstanding_balance_cents": calc.outstanding_balance(c["id"]),
        "credit_balance_cents": c["credit_balance_cents"],
        "safety_rating": c["safety_rating"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def security_plan(p):
    return {
        "id": p["id"],
        "carrier_id": p["carrier_id"],
        "plan_name": p["plan_name"],
        "coverage_categories": list(p["coverage_categories"]),
        "effective_from": fmt_dt(p["effective_from"]),
        "effective_to": fmt_dt(p["effective_to"]),
        "status": p["status"],
        "approved_at": fmt_dt(p["approved_at"]),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def material(m):
    return {
        "id": m["id"],
        "un_na_number": m["un_na_number"],
        "proper_shipping_name": m["proper_shipping_name"],
        "hazard_class": m["hazard_class"],
        "packing_group": m["packing_group"],
        "placard_table": m["placard_table"],
        "transport_category": m["transport_category"],
        "reportable_quantity_lbs": m["reportable_quantity_lbs"],
        "is_inhalation_hazard": m["is_inhalation_hazard"],
        "segregation_group": m["segregation_group"],
        "erg_guide_number": m["erg_guide_number"],
        "requires_security_plan": calc.material_requires_security_plan(m),
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def spec(s):
    return {
        "id": s["id"],
        "spec_code": s["spec_code"],
        "authorized_hazard_classes": list(s["authorized_hazard_classes"]),
        "max_packing_group": s["max_packing_group"],
        "max_net_quantity_kg": s["max_net_quantity_kg"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def driver(d):
    return {
        "id": d["id"],
        "carrier_id": d["carrier_id"],
        "full_name": d["full_name"],
        "cdl_number": d["cdl_number"],
        "hazmat_endorsement_expires_at": fmt_dt(d["hazmat_endorsement_expires_at"]),
        "status": d["status"],
        "qualification_posture": calc.driver_posture(d),
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def training_record(r):
    return {
        "id": r["id"],
        "driver_id": r["driver_id"],
        "training_type": r["training_type"],
        "completed_at": fmt_dt(r["completed_at"]),
        "expires_at": fmt_dt(r["expires_at"]),
        "certificate_code": r["certificate_code"],
        "created_at": fmt_dt(r["created_at"]),
    }


def vehicle(v):
    return {
        "id": v["id"],
        "carrier_id": v["carrier_id"],
        "plate_number": v["plate_number"],
        "vehicle_class": v["vehicle_class"],
        "status": v["status"],
        "created_at": fmt_dt(v["created_at"]),
        "updated_at": fmt_dt(v["updated_at"]),
        "version": v["version"],
    }


def shipment(s):
    return {
        "id": s["id"],
        "carrier_id": s["carrier_id"],
        "material_id": s["material_id"],
        "packaging_spec_id": s["packaging_spec_id"],
        "driver_id": s["driver_id"],
        "declared_shipping_name": s["declared_shipping_name"],
        "normalized_shipping_name": s["normalized_shipping_name"],
        "quantity_kg": s["quantity_kg"],
        "declared_value_cents": s["declared_value_cents"],
        "status": s["status"],
        "classified_by_user_id": s["classified_by_user_id"],
        "pinned_security_plan_id": s["pinned_security_plan_id"],
        "pinned_security_plan_version": s["pinned_security_plan_version"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def shipping_paper(p):
    return {
        "id": p["id"],
        "shipment_id": p["shipment_id"],
        "emergency_contact_phone": p["emergency_contact_phone"],
        "er_response_guide_number": p["er_response_guide_number"],
        "emergency_response_summary": p["emergency_response_summary"],
        "shipper_certification_signed": p["shipper_certification_signed"],
        "certified_by_user_id": p["certified_by_user_id"],
        "amendment_count": p["amendment_count"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def vehicle_load(l):
    return {
        "id": l["id"],
        "vehicle_id": l["vehicle_id"],
        "route_id": l["route_id"],
        "planned_departure_at": fmt_dt(l["planned_departure_at"]),
        "planned_arrival_at": fmt_dt(l["planned_arrival_at"]),
        "total_table2_weight_kg": float(l["total_table2_weight_kg"]),
        "required_placards": list(l["required_placards"]),
        "handling_fee_cents": l["handling_fee_cents"],
        "status": l["status"],
        "created_at": fmt_dt(l["created_at"]),
        "updated_at": fmt_dt(l["updated_at"]),
        "version": l["version"],
    }


def load_item(i):
    return {
        "id": i["id"],
        "load_id": i["load_id"],
        "shipment_id": i["shipment_id"],
        "position_code": i["position_code"],
        "created_at": fmt_dt(i["created_at"]),
    }


def route(r):
    return {
        "id": r["id"],
        "route_code": r["route_code"],
        "allowed_hazard_classes": list(r["allowed_hazard_classes"]),
        "is_restricted_corridor": r["is_restricted_corridor"],
        "effective_from": fmt_dt(r["effective_from"]),
        "effective_to": fmt_dt(r["effective_to"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def incident(i):
    return {
        "id": i["id"],
        "shipment_id": i["shipment_id"],
        "carrier_id": i["carrier_id"],
        "occurred_at": fmt_dt(i["occurred_at"]),
        "severity": i["severity"],
        "confirmed_severity": i["confirmed_severity"],
        "phone_report_required": i["phone_report_required"],
        "phone_deadline": fmt_dt(i["phone_deadline"]),
        "written_report_deadline": fmt_dt(i["written_report_deadline"]),
        "phone_reported_at": fmt_dt(i["phone_reported_at"]),
        "written_filed_at": fmt_dt(i["written_filed_at"]),
        "is_phone_late": calc.is_phone_late(i),
        "is_written_late": calc.is_written_late(i),
        "penalty_cents": i["penalty_cents"],
        "status": i["status"],
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def invoice(inv):
    return {
        "id": inv["id"],
        "carrier_id": inv["carrier_id"],
        "kind": inv["kind"],
        "assessment_year": inv["assessment_year"],
        "provisional_total_cents": inv["provisional_total_cents"],
        "final_total_cents": inv["final_total_cents"],
        "total_due_cents": inv["total_due_cents"],
        "paid_cents": inv["paid_cents"],
        "status": inv["status"],
        "created_at": fmt_dt(inv["created_at"]),
        "updated_at": fmt_dt(inv["updated_at"]),
        "version": inv["version"],
    }
