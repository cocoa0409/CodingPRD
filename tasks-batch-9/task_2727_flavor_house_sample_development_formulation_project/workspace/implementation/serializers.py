"""Entity -> JSON representations (field names exactly as scaffold §1.1)."""

from db import iso, num
from services import graph, ledger


def _common(entity, payload):
    payload["id"] = entity["id"]
    payload["created_at"] = iso(entity["created_at"])
    payload["updated_at"] = iso(entity["updated_at"])
    payload["version"] = entity["version"]
    return payload


def brief_out(brief):
    return _common(brief, {
        "brief_code": brief["brief_code"],
        "customer_name": brief["customer_name"],
        "matrix_type": brief["matrix_type"],
        "target_profile": brief["target_profile"],
        "dosage_pct": num(brief["dosage_pct"]),
        "annual_volume_kg": brief["annual_volume_kg"],
        "cost_in_use_cap_cents_per_tonne": brief["cost_in_use_cap_cents_per_tonne"],
        "natural_claim_required": brief["natural_claim_required"],
        "kosher_required": brief["kosher_required"],
        "halal_required": brief["halal_required"],
        "allergen_exclusions": list(brief["allergen_exclusions"]),
        "confidentiality_tier": brief["confidentiality_tier"],
        "status": brief["status"],
        "clarification_round_count": brief["clarification_round_count"],
        "clarification_note": brief["clarification_note"],
        "decision_note": brief["decision_note"],
        "outcome": brief["outcome"],
        "loss_reason": brief["loss_reason"],
        "closed_at": iso(brief["closed_at"]),
    })


def material_out(material):
    return _common(material, {
        "material_code": material["material_code"],
        "name": material["name"],
        "cost_per_kg_cents": material["cost_per_kg_cents"],
        "natural_status": material["natural_status"],
        "potency_class": material["potency_class"],
        "max_use_ppm": material["max_use_ppm"],
        "allergen_codes": list(material["allergen_codes"]),
        "claim_status": graph.material_claim_status(material["id"]),
        "verified_claim_types": graph.material_verified_claim_types(material["id"]),
    })


def record_out(record):
    from db import now_logical
    return _common(record, {
        "raw_material_id": record["raw_material_id"],
        "claim_type": record["claim_type"],
        "issuing_body": record["issuing_body"],
        "document_ref": record["document_ref"],
        "valid_until": iso(record["valid_until"]),
        "status": record["status"],
        "verified_at": iso(record["verified_at"]),
        "revocation_reason": record["revocation_reason"],
        "is_expired": record["valid_until"] < now_logical(),
    })


def formula_out(formula):
    return _common(formula, {
        "brief_id": formula["brief_id"],
        "parent_formula_id": formula["parent_formula_id"],
        "superseded_by_formula_id": formula["superseded_by_formula_id"],
        "name": formula["name"],
        "iteration_no": formula["iteration_no"],
        "confidentiality_tier": formula["confidentiality_tier"],
        "status": formula["status"],
        "component_count": graph.component_count(formula["id"]),
        "total_weight_pct": num(graph.total_weight_pct(formula["id"])),
        "bench_cost_per_kg_cents": formula["bench_cost_per_kg_cents"],
        "bench_cost_in_use_cents_per_tonne":
            formula["bench_cost_in_use_cents_per_tonne"],
        "firm_cost_in_use_cents_per_tonne":
            formula["firm_cost_in_use_cents_per_tonne"],
        "allergen_codes": list(formula["allergen_codes"]),
        "natural_claim_eligible": formula["natural_claim_eligible"],
        "kosher_eligible": formula["kosher_eligible"],
        "halal_eligible": formula["halal_eligible"],
        "cost_stale": formula["cost_stale"],
        "submitted_by_user_id": formula["submitted_by_user_id"],
        "approved_by_user_id": formula["approved_by_user_id"],
        "rework_reason": formula["rework_reason"],
    })


def component_out(component, sequence_no=None):
    if sequence_no is None:
        sequence_no = graph.sequence_no_of(component)
    return _common(component, {
        "formula_id": component["formula_id"],
        "component_type": component["component_type"],
        "raw_material_id": component["raw_material_id"],
        "sub_formula_id": component["sub_formula_id"],
        "weight_pct": num(component["weight_pct"]),
        "sequence_no": sequence_no,
        "contribution_cents": component["contribution_cents"],
    })


def _weight_bucket(weight):
    for ceiling, label in ((1, "0-1"), (5, "1-5"), (10, "5-10"), (25, "10-25"),
                           (50, "25-50")):
        if weight <= ceiling:
            return label
    return "50-100"


def component_redacted_out(component, sequence_no=None):
    """REDACTED grants hide material identity and bucket the weights (§2.9)."""
    if sequence_no is None:
        sequence_no = graph.sequence_no_of(component)
    return _common(component, {
        "formula_id": component["formula_id"],
        "component_type": component["component_type"],
        "raw_material_id": None,
        "sub_formula_id": None,
        "weight_pct": None,
        "weight_bucket": _weight_bucket(component["weight_pct"]),
        "sequence_no": sequence_no,
        "contribution_cents": None,
    })


def lot_out(lot):
    allocated = ledger.allocated_g(lot["id"])
    return _common(lot, {
        "formula_id": lot["formula_id"],
        "lot_number": lot["lot_number"],
        "formula_iteration_no": lot["formula_iteration_no"],
        "batch_size_g": lot["batch_size_g"],
        "qc_status": lot["qc_status"],
        "disposition_status": lot["disposition_status"],
        "allocated_g": allocated,
        "available_g": lot["batch_size_g"] - allocated,
        "compounded_by_user_id": lot["compounded_by_user_id"],
        "qc_by_user_id": lot["qc_by_user_id"],
    })


def cabinet_out(cabinet):
    return _common(cabinet, {
        "cabinet_code": cabinet["cabinet_code"],
        "capacity_slots": cabinet["capacity_slots"],
        "storage_temp_c": num(cabinet["storage_temp_c"]),
        "slots_available": ledger.slots_available(cabinet),
    })


def retention_out(row):
    return _common(row, {
        "sample_lot_id": row["sample_lot_id"],
        "cabinet_id": row["cabinet_id"],
        "quantity_g": row["quantity_g"],
        "slot_count": row["slot_count"],
        "stored_from": iso(row["stored_from"]),
        "stored_until": iso(row["stored_until"]),
        "status": row["status"],
        "withdrawal_reason": row["withdrawal_reason"],
        "withdrawn_at": iso(row["withdrawn_at"]),
    })


def rig_out(rig):
    return _common(rig, {
        "rig_code": rig["rig_code"],
        "matrix_type": rig["matrix_type"],
        "cleanout_buffer_minutes": rig["cleanout_buffer_minutes"],
    })


def test_out(test):
    return _common(test, {
        "sample_lot_id": test["sample_lot_id"],
        "rig_id": test["rig_id"],
        "window_start": iso(test["window_start"]),
        "window_end": iso(test["window_end"]),
        "dosage_pct": num(test["dosage_pct"]),
        "consumed_g": test["consumed_g"],
        "status": test["status"],
        "aroma_score": num(test["aroma_score"]),
        "taste_score": num(test["taste_score"]),
        "stability_score": num(test["stability_score"]),
        "panel_score": num(test["panel_score"]),
        "verdict_recorded_at": iso(test["verdict_recorded_at"]),
    })


def shipment_out(shipment):
    return _common(shipment, {
        "sample_lot_id": shipment["sample_lot_id"],
        "brief_id": shipment["brief_id"],
        "destination_country": shipment["destination_country"],
        "shipped_g": shipment["shipped_g"],
        "carrier": shipment["carrier"],
        "status": shipment["status"],
        "required_document_types": list(shipment["required_document_types"]),
        "packet_valid_until": iso(shipment["packet_valid_until"]),
        "tracking_reference": shipment["tracking_reference"],
        "dispatched_at": iso(shipment["dispatched_at"]),
        "block_reason": shipment["block_reason"],
        "cancellation_reason": shipment["cancellation_reason"],
    })


def document_out(document):
    return _common(document, {
        "shipment_id": document["shipment_id"],
        "doc_type": document["doc_type"],
        "substantiation_id": document["substantiation_id"],
        "pinned_substantiation_version": document["pinned_substantiation_version"],
        "pinned_valid_until": iso(document["pinned_valid_until"]),
        "status": document["status"],
        "generated_at": iso(document["generated_at"]),
    })


def batch_out(batch):
    spec = []
    for entry in batch["tolerance_spec"]:
        spec.append({
            "component_id": entry["component_id"],
            "weight_pct": num(entry["weight_pct"]),
            "band_pct": num(entry["band_pct"]),
        })
    return _common(batch, {
        "formula_id": batch["formula_id"],
        "target_kg": batch["target_kg"],
        "pinned_formula_version": batch["pinned_formula_version"],
        "status": batch["status"],
        "material_cost_cents": batch["material_cost_cents"],
        "compounding_fee_pct": num(batch["compounding_fee_pct"]),
        "compounding_fee_cents": batch["compounding_fee_cents"],
        "batch_total_cents": batch["batch_total_cents"],
        "production_cost_per_kg_cents": batch["production_cost_per_kg_cents"],
        "tolerance_spec": spec,
        "measured_yield_kg": num(batch["measured_yield_kg"]),
        "yield_variance_pct": num(batch["yield_variance_pct"]),
        "decision_note": batch["decision_note"],
        "cancellation_reason": batch["cancellation_reason"],
    })


def forecast_out(forecast):
    return _common(forecast, {
        "brief_id": forecast["brief_id"],
        "annual_volume_kg": forecast["annual_volume_kg"],
        "unit_price_cents_per_kg": forecast["unit_price_cents_per_kg"],
        "pinned_brief_version": forecast["pinned_brief_version"],
        "variant_applied": forecast["variant_applied"],
        "stage_probability": num(forecast["stage_probability"]),
        "technical_factor": num(forecast["technical_factor"]),
        "weighted_annual_value_cents": forecast["weighted_annual_value_cents"],
        "status": forecast["status"],
    })


def grant_out(grant):
    from db import now_logical
    status = "ACTIVE" if now_logical() < grant["expires_at"] else "EXPIRED"
    return _common(grant, {
        "brief_id": grant["brief_id"],
        "formula_id": grant["formula_id"],
        "disclosed_tier": grant["disclosed_tier"],
        "redaction_level": grant["redaction_level"],
        "expires_at": iso(grant["expires_at"]),
        "status": status,
    })
