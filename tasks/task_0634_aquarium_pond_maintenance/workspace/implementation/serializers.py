"""Public serialization of each entity to its API representation.

Field names trace verbatim to SCAFFOLD §1.1 entities and the PRD.
Common fields (id, created_at, updated_at, version) are emitted for every
entity except WaterTest, which carries only id + created_at (PRD §2.4).
"""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def contract_view(r):
    out = _common(r)
    out.update({
        "customer_name": r["customer_name"],
        "customer_user_id": r["customer_user_id"],
        "service_tier": r["service_tier"],
        "status": r["status"],
        "route_day": r["route_day"],
        "account_balance_cents": r["account_balance_cents"],
        "alive_livestock_count": r["alive_livestock_count"],
    })
    return out


def system_view(r):
    out = _common(r)
    out.update({
        "contract_id": r["contract_id"],
        "label": r["label"],
        "system_kind": r["system_kind"],
        "nominal_volume_l": r["nominal_volume_l"],
        "substrate_displacement_pct": r["substrate_displacement_pct"],
        "status": r["status"],
        "bioload_index": r["bioload_index"],
        "stocking_posture": r["stocking_posture"],
    })
    return out


def livestock_view(r):
    out = _common(r)
    out.update({
        "system_id": r["system_id"],
        "common_name": r["common_name"],
        "species_class": r["species_class"],
        "adult_length_cm": r["adult_length_cm"],
        "status": r["status"],
    })
    return out


def equipment_view(r):
    out = _common(r)
    out.update({
        "system_id": r["system_id"],
        "device_kind": r["device_kind"],
        "media_interval_days": r["media_interval_days"],
        "last_serviced_on": r["last_serviced_on"],
        "media_due_on": r["media_due_on"],
        "status": r["status"],
    })
    return out


def technician_view(r):
    out = _common(r)
    out.update({
        "tech_user_id": r["tech_user_id"],
        "full_name": r["full_name"],
        "certified_for_reef": r["certified_for_reef"],
        "active": r["active"],
    })
    return out


def visit_view(r):
    out = _common(r)
    out.update({
        "system_id": r["system_id"],
        "technician_id": r["technician_id"],
        "visit_kind": r["visit_kind"],
        "emergency_call_id": r["emergency_call_id"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "labor_minutes": r["labor_minutes"],
        "status": r["status"],
        "total_cents": r["total_cents"],
        "invoice_id": r["invoice_id"],
    })
    return out


def water_test_view(r):
    # WaterTest carries only id + created_at, plus its data fields (PRD §2.4/§3.5)
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "visit_id": r["visit_id"],
        "parameter": r["parameter"],
        "measured_value": r["measured_value"],
        "target_value": r["target_value"],
        "product_strength_ppm_per_ml": r["product_strength_ppm_per_ml"],
        "recommended_dose_ml": r["recommended_dose_ml"],
    }


def invoice_view(r):
    out = _common(r)
    out.update({
        "contract_id": r["contract_id"],
        "source_kind": r["source_kind"],
        "source_id": r["source_id"],
        "total_cents": r["total_cents"],
        "amount_paid_cents": r["amount_paid_cents"],
        "status": r["status"],
        "due_on": r["due_on"],
    })
    return out


def install_view(r):
    out = _common(r)
    out.update({
        "contract_id": r["contract_id"],
        "system_id": r["system_id"],
        "labor_estimate_cents": r["labor_estimate_cents"],
        "equipment_estimate_cents": r["equipment_estimate_cents"],
        "actual_labor_minutes": r["actual_labor_minutes"],
        "actual_equipment_cents": r["actual_equipment_cents"],
        "change_order_cents": r["change_order_cents"],
        "quote_total_cents": r["quote_total_cents"],
        "deposit_cents": r["deposit_cents"],
        "final_total_cents": r["final_total_cents"],
        "status": r["status"],
    })
    return out


def emergency_view(r):
    out = _common(r)
    out.update({
        "system_id": r["system_id"],
        "severity": r["severity"],
        "reported_at": r["reported_at"],
        "trip_fee_cents": r["trip_fee_cents"],
        "status": r["status"],
        "dispatched_visit_id": r["dispatched_visit_id"],
    })
    return out


def repair_view(r):
    out = _common(r)
    out.update({
        "equipment_id": r["equipment_id"],
        "reported_symptom": r["reported_symptom"],
        "parts_needed": r["parts_needed"],
        "status": r["status"],
    })
    return out


def quarantine_view(r):
    out = _common(r)
    out.update({
        "livestock_id": r["livestock_id"],
        "quarantine_tank_id": r["quarantine_tank_id"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
    })
    return out


def feeding_plan_view(r):
    out = _common(r)
    out.update({
        "system_id": r["system_id"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "feedings_per_day": r["feedings_per_day"],
        "status": r["status"],
    })
    return out
