"""Entity serializers — resolve computed fields at read time."""
from decimal import Decimal

from db import store
from services import domain


def _num(x, places: int):
    """Format a Decimal as int (places=0) or float with given decimal places."""
    if x is None:
        return None
    d = x if isinstance(x, Decimal) else Decimal(str(x))
    if places == 0:
        return int(d)
    return float(d.quantize(Decimal(1).scaleb(-places)))


def serialize_site(site: dict) -> dict:
    out = {
        "id": site["id"],
        "name": site["name"],
        "state_code": site["state_code"],
        "contract_discount_pct": _num(Decimal(str(site.get("contract_discount_pct", 0))), 2)
            if not float(site.get("contract_discount_pct", 0)).is_integer() else int(site.get("contract_discount_pct", 0)),
        "capital_threshold_cents": int(site.get("capital_threshold_cents", 500000)),
        "credit_hold": bool(site.get("credit_hold", False)),
        "site_posture": domain.compute_site_posture(site["id"]),
        "created_at": site["created_at"],
        "updated_at": site["updated_at"],
        "version": site["version"],
    }
    return out


def _num_preserve(x):
    """Return the value as int if integral, else float. Input is a Python number."""
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    f = float(x)
    return int(f) if f.is_integer() else f


def serialize_technician(t: dict) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "weekly_capacity_hours": _num_preserve(t["weekly_capacity_hours"]),
        "certifications": list(t.get("certifications", [])),
        "active": bool(t.get("active", True)),
        "remaining_capacity_hours": float(domain.compute_remaining_capacity_hours(t)),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_vessel(v: dict) -> dict:
    current_inv = domain.compute_current_inventory_tons(v)
    out = {
        "id": v["id"],
        "site_id": v["site_id"],
        "name": v["name"],
        "vessel_kind": v["vessel_kind"],
        "capacity_tons": _num_preserve(v["capacity_tons"]),
        "material_name": v["material_name"],
        "opening_inventory_tons": _num_preserve(v.get("opening_inventory_tons", 0)),
        "reorder_point_pct": _num_preserve(v["reorder_point_pct"]),
        "target_fill_pct": _num_preserve(v.get("target_fill_pct", 90)),
        "replenishment_policy": v.get("replenishment_policy", "TARGET_FILL"),
        "cover_days": _num_preserve(v.get("cover_days", 7)),
        "default_usage_tons": _num_preserve(v.get("default_usage_tons", 1.0)),
        "moisture_limit_pct": _num_preserve(v.get("moisture_limit_pct", 12.0)),
        "error_basis": v.get("error_basis", "OF_READING"),
        "full_scale_tons": (_num_preserve(v["full_scale_tons"]) if v.get("full_scale_tons") is not None else None),
        "current_inventory_tons": float(current_inv),
        "flow_posture": domain.compute_flow_posture(v),
        "scale_status": v.get("scale_status", "IN_TOLERANCE"),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }
    return out


def serialize_level_reading(r: dict) -> dict:
    return {
        "id": r["id"],
        "vessel_id": r["vessel_id"],
        "measured_at": r["measured_at"],
        "level_pct": _num_preserve(r["level_pct"]),
        "source": r.get("source", "MANUAL"),
        "created_at": r["created_at"],
    }


def serialize_quality_report(r: dict) -> dict:
    return {
        "id": r["id"],
        "vessel_id": r["vessel_id"],
        "sampled_at": r["sampled_at"],
        "moisture_pct": _num_preserve(r["moisture_pct"]),
        "caking_index": int(r["caking_index"]),
        "flowability_grade": r["flowability_grade"],
        "created_at": r["created_at"],
    }


def serialize_scale_calibration(c: dict) -> dict:
    return {
        "id": c["id"],
        "vessel_id": c["vessel_id"],
        "tested_at": c["tested_at"],
        "test_weight_tons": _num_preserve(c["test_weight_tons"]),
        "indicated_tons": _num_preserve(c["indicated_tons"]),
        "tolerance_pct": _num_preserve(c.get("tolerance_pct", 0.25)),
        "error_basis_used": c["error_basis_used"],
        "error_pct": float(c["error_pct"]),
        "result": c["result"],
        "created_at": c["created_at"],
    }


def serialize_order(o: dict) -> dict:
    return {
        "id": o["id"],
        "vessel_id": o["vessel_id"],
        "trigger_reading_id": o.get("trigger_reading_id"),
        "policy_used": o.get("policy_used"),
        "order_quantity_tons": float(o["order_quantity_tons"]) if o.get("order_quantity_tons") is not None else None,
        "status": o["status"],
        "delivered_tons": (_num_preserve(o["delivered_tons"]) if o.get("delivered_tons") is not None else None),
        "received_at": o.get("received_at"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_ticket(t: dict) -> dict:
    return {
        "id": t["id"],
        "site_id": t["site_id"],
        "vessel_id": t["vessel_id"],
        "technician_id": t.get("technician_id"),
        "source_permit_id": t.get("source_permit_id"),
        "job_type": t["job_type"],
        "requires_entry": bool(t["requires_entry"]),
        "est_hours": _num_preserve(t["est_hours"]),
        "crew_size": int(t["crew_size"]),
        "description": t.get("description", ""),
        "status": t["status"],
        "estimate_cents": t.get("estimate_cents"),
        "commercial_track": t.get("commercial_track"),
        "window_start": t.get("window_start"),
        "window_end": t.get("window_end"),
        "actual_hours": (_num_preserve(t["actual_hours"]) if t.get("actual_hours") is not None else None),
        "mileage_miles": (_num_preserve(t["mileage_miles"]) if t.get("mileage_miles") is not None else None),
        "disposal_tons": (_num_preserve(t["disposal_tons"]) if t.get("disposal_tons") is not None else None),
        "invoice_labor_cents": t.get("invoice_labor_cents"),
        "invoice_mobilization_cents": t.get("invoice_mobilization_cents"),
        "invoice_disposal_cents": t.get("invoice_disposal_cents"),
        "invoice_subtotal_cents": t.get("invoice_subtotal_cents"),
        "invoice_discount_cents": t.get("invoice_discount_cents"),
        "invoice_tax_cents": t.get("invoice_tax_cents"),
        "invoice_total_cents": t.get("invoice_total_cents"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_permit(p: dict) -> dict:
    return {
        "id": p["id"],
        "vessel_id": p["vessel_id"],
        "ticket_id": p["ticket_id"],
        "entrant_technician_id": p["entrant_technician_id"],
        "issuer_user_id": p.get("issuer_user_id"),
        "window_start": p["window_start"],
        "window_end": p["window_end"],
        "lockout_checklist_confirmed": bool(p.get("lockout_checklist_confirmed", False)),
        "atmosphere_ok": p.get("atmosphere_ok"),
        "last_oxygen_pct": (_num_preserve(p["last_oxygen_pct"]) if p.get("last_oxygen_pct") is not None else None),
        "last_combustible_pct": (_num_preserve(p["last_combustible_pct"]) if p.get("last_combustible_pct") is not None else None),
        "status": p["status"],
        "void_reason": p.get("void_reason", "NONE"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
