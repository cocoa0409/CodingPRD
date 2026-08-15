"""Entity -> JSON-serializable dict, with computed/read-time fields applied."""
from decimal import Decimal

from db import store, get_clock
from services import chemistry


def _num(v):
    """Convert Decimal to float for JSON output; pass through other values."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def customer_view(c):
    return {
        "id": c["id"],
        "company_name": c["company_name"],
        "priority_tier": c["priority_tier"],
        "credit_hold": c["credit_hold"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def fixture_view(f):
    return {
        "id": f["id"],
        "fixture_code": f["fixture_code"],
        "routing_mode": f["routing_mode"],
        "capacity_dm2": _num(f["capacity_dm2"]),
        "purchase_cost_cents": f["purchase_cost_cents"],
        "rated_uses": f["rated_uses"],
        "amortization_cents_per_use": f["amortization_cents_per_use"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def compat_rule_view(r):
    return {
        "id": r["id"],
        "alloy_code": r["alloy_code"],
        "process_type": r["process_type"],
        "chemistry_family": r["chemistry_family"],
        "compatibility": r["compatibility"],
        "notes": r.get("notes"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def bath_view(b):
    return {
        "id": b["id"],
        "bath_code": b["bath_code"],
        "process_type": b["process_type"],
        "chemistry_family": b["chemistry_family"],
        "routing_modes_supported": list(b["routing_modes_supported"]),
        "volume_liters": _num(b["volume_liters"]),
        "target_concentration_g_l": _num(b["target_concentration_g_l"]),
        "low_concentration_g_l": _num(b["low_concentration_g_l"]),
        "high_concentration_g_l": _num(b["high_concentration_g_l"]),
        "amp_hour_capacity": _num(b["amp_hour_capacity"]),
        "current_concentration_g_l": _num(b["current_concentration_g_l"]) if b["current_concentration_g_l"] is not None else None,
        "amp_hour_used": _num(b["amp_hour_used"]),
        "amp_hour_reserved": _num(b["amp_hour_reserved"]),
        "active_load_run_id": b["active_load_run_id"],
        "dose_verification_pending": b["dose_verification_pending"],
        "quarantine_cause": b["quarantine_cause"],
        "status": b["status"],
        "nameplate_remaining_ah": _num(chemistry.nameplate_remaining_ah(b)),
        "effective_remaining_ah": chemistry.effective_remaining_ah(b),
        "recommended_dose_g": chemistry.recommended_dose_g(b),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def titration_view(t):
    return {
        "id": t["id"],
        "bath_id": t["bath_id"],
        "titrant_volume_ml": _num(t["titrant_volume_ml"]),
        "titrant_normality": _num(t["titrant_normality"]),
        "sample_volume_ml": _num(t["sample_volume_ml"]),
        "measured_concentration_g_l": _num(t["measured_concentration_g_l"]),
        "created_at": t["created_at"],
    }


def dose_view(d):
    return {
        "id": d["id"],
        "bath_id": d["bath_id"],
        "chemical_code": d["chemical_code"],
        "quantity_g": _num(d["quantity_g"]),
        "resulting_concentration_g_l": _num(d["resulting_concentration_g_l"]),
        "created_at": d["created_at"],
    }


def work_order_view(w):
    return {
        "id": w["id"],
        "customer_id": w["customer_id"],
        "part_number": w["part_number"],
        "alloy_code": w["alloy_code"],
        "process_type": w["process_type"],
        "routing_mode": w["routing_mode"],
        "part_count": w["part_count"],
        "surface_area_dm2_per_part": _num(w["surface_area_dm2_per_part"]),
        "surface_area_total_dm2": _num(w["surface_area_total_dm2"]),
        "thickness_spec_min_um": _num(w["thickness_spec_min_um"]),
        "thickness_spec_max_um": _num(w["thickness_spec_max_um"]),
        "requires_masking": w["requires_masking"],
        "masking_minutes_actual": w["masking_minutes_actual"],
        "requires_salt_spray": w["requires_salt_spray"],
        "predip_completed": w["predip_completed"],
        "bath_id": w["bath_id"],
        "fixture_id": w["fixture_id"],
        "routed_chemistry_family": w["routed_chemistry_family"],
        "rework_count": w["rework_count"],
        "pending_strip": w["pending_strip"],
        "last_defect_type": w["last_defect_type"],
        "provisional_quote_cents": w["provisional_quote_cents"],
        "final_invoice_cents": w["final_invoice_cents"],
        "completed_load_count": w["completed_load_count"],
        "cancellation_fee_cents": w["cancellation_fee_cents"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def load_run_view(r):
    return {
        "id": r["id"],
        "work_order_id": r["work_order_id"],
        "bath_id": r["bath_id"],
        "fixture_id": r["fixture_id"],
        "duration_minutes": r["duration_minutes"],
        "current_density_a_dm2": _num(r["current_density_a_dm2"]),
        "surface_area_dm2": _num(r["surface_area_dm2"]),
        "estimated_amp_hours": _num(r["estimated_amp_hours"]),
        "amp_hours_consumed": _num(r["amp_hours_consumed"]) if r["amp_hours_consumed"] is not None else None,
        "started_at": r["started_at"],
        "ended_at": r["ended_at"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def inspection_view(i):
    return {
        "id": i["id"],
        "work_order_id": i["work_order_id"],
        "load_run_id": i["load_run_id"],
        "thickness_readings_um": [_num(x) for x in i["thickness_readings_um"]],
        "defect_type": i["defect_type"],
        "thickness_min_um": _num(i["thickness_min_um"]),
        "thickness_max_um": _num(i["thickness_max_um"]),
        "thickness_ok": i["thickness_ok"],
        "disposition": i["disposition"],
        "created_at": i["created_at"],
    }


def salt_spray_lot_view(lot):
    return {
        "id": lot["id"],
        "work_order_id": lot["work_order_id"],
        "sample_count": lot["sample_count"],
        "hours_required": lot["hours_required"],
        "allowed_failures": lot["allowed_failures"],
        "panels_failed": lot["panels_failed"],
        "hours_run": lot_hours_run(lot),
        "result": lot["result"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def lot_hours_run(lot):
    """floor((current_utc - created_at) in whole hours), using the logical clock."""
    from helpers import parse_iso8601  # local import to avoid cycle
    created = parse_iso8601(lot["created_at"])
    delta = get_clock() - created
    hours = int(delta.total_seconds() // 3600)
    return max(hours, 0)


def permit_view(p):
    return {
        "id": p["id"],
        "outfall_code": p["outfall_code"],
        "effective_from": p["effective_from"],
        "effective_to": p["effective_to"],
        "limits": [
            {
                "analyte_code": l["analyte_code"],
                "max_concentration_mg_l": _num(l["max_concentration_mg_l"]),
                "monthly_mass_cap_g": _num(l["monthly_mass_cap_g"]),
            }
            for l in p["limits"]
        ],
        "current_month": p["current_month"],
        "cumulative_mass_g": {k: _num(v) for k, v in p["cumulative_mass_g"].items()},
        "last_sampled_at": p["last_sampled_at"],
        "exceedance_active": p["exceedance_active"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def sample_view(s):
    return {
        "id": s["id"],
        "permit_id": s["permit_id"],
        "sampled_at": s["sampled_at"],
        "flow_liters": _num(s["flow_liters"]),
        "readings": [
            {"analyte_code": r["analyte_code"], "concentration_mg_l": _num(r["concentration_mg_l"])}
            for r in s["readings"]
        ],
        "masses_g": {k: _num(v) for k, v in s["masses_g"].items()},
        "is_exceedance": s["is_exceedance"],
        "created_at": s["created_at"],
    }


def manifest_view(m):
    return {
        "id": m["id"],
        "generator_epa_id": m["generator_epa_id"],
        "transporter_name": m["transporter_name"],
        "created_by_user_id": m["created_by_user_id"],
        "finalized_by_user_id": m["finalized_by_user_id"],
        "total_mass_kg": _num(m["total_mass_kg"]),
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def manifest_line_item_view(li):
    return {
        "id": li["id"],
        "manifest_id": li["manifest_id"],
        "waste_code": li["waste_code"],
        "source_type": li["source_type"],
        "description": li["description"],
        "volume_liters": _num(li["volume_liters"]),
        "mass_kg": _num(li["mass_kg"]),
        "origin_bath_id": li["origin_bath_id"],
        "created_at": li["created_at"],
        "updated_at": li["updated_at"],
        "version": li["version"],
    }
