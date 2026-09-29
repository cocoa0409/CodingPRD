"""Payload factories - one per entity, client-supplied input fields only.

Every monetary field is an integer number of cents and every gram or
kilogram quantity is an integer; they are emitted as JSON numbers, never
as strings.
"""

from typing import Any, Dict, Optional

DEFAULTS: Dict[str, Any] = {
    "BRIEF_CODE": "BRF-0001",
    "CUSTOMER_NAME": "Nordica Dairy",
    "MATRIX_TYPE": "DAIRY_YOGURT",
    "TARGET_PROFILE": "VANILLA_CREAM",
    "DOSAGE_PCT": 1.0,
    "ANNUAL_VOLUME_KG": 500,
    "COST_IN_USE_CAP_CENTS_PER_TONNE": 100000,
    "CONFIDENTIALITY_TIER": "TIER_1_STANDARD",
    "MATERIAL_CODE": "GUM-BASE",
    "MATERIAL_NAME": "Gum Base 40",
    "COST_PER_KG_CENTS": 2000,
    "NATURAL_STATUS": "NATURE_IDENTICAL",
    "POTENCY_CLASS": "STANDARD",
    "MAX_USE_PPM": 1000000,
    "FORMULA_NAME": "Vanilla Cream F1",
    "ISSUING_BODY": "OU",
    "DOCUMENT_REF": "K-2026-1",
    "VALID_UNTIL": "2027-12-31T00:00:00Z",
    "BATCH_SIZE_G": 500,
    "CABINET_CODE": "CAB-01",
    "CAPACITY_SLOTS": 10,
    "STORAGE_TEMP_C": 4.0,
    "RIG_CODE": "RIG-BEV-01",
    "CLEANOUT_BUFFER_MINUTES": 30,
    "DESTINATION_COUNTRY": "US",
    "TARGET_KG": 150,
    "UNIT_PRICE_CENTS_PER_KG": 10000,
    "REDACTION_LEVEL": "FULL",
}


def create_customer_brief_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "brief_code": DEFAULTS["BRIEF_CODE"],
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "matrix_type": DEFAULTS["MATRIX_TYPE"],
        "target_profile": DEFAULTS["TARGET_PROFILE"],
        "dosage_pct": DEFAULTS["DOSAGE_PCT"],
        "annual_volume_kg": DEFAULTS["ANNUAL_VOLUME_KG"],
        "cost_in_use_cap_cents_per_tonne":
            DEFAULTS["COST_IN_USE_CAP_CENTS_PER_TONNE"],
        "confidentiality_tier": DEFAULTS["CONFIDENTIALITY_TIER"],
    }
    payload.update(overrides)
    return payload


def create_raw_material_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "material_code": DEFAULTS["MATERIAL_CODE"],
        "name": DEFAULTS["MATERIAL_NAME"],
        "cost_per_kg_cents": DEFAULTS["COST_PER_KG_CENTS"],
        "natural_status": DEFAULTS["NATURAL_STATUS"],
        "potency_class": DEFAULTS["POTENCY_CLASS"],
        "max_use_ppm": DEFAULTS["MAX_USE_PPM"],
    }
    payload.update(overrides)
    return payload


def reprice_raw_material_payload(cost_per_kg_cents: int, **overrides) -> Dict[str, Any]:
    payload = {"cost_per_kg_cents": cost_per_kg_cents}
    payload.update(overrides)
    return payload


def create_substantiation_record_payload(raw_material_id: str,
                                         claim_type: str,
                                         **overrides) -> Dict[str, Any]:
    payload = {
        "raw_material_id": raw_material_id,
        "claim_type": claim_type,
        "issuing_body": DEFAULTS["ISSUING_BODY"],
        "document_ref": DEFAULTS["DOCUMENT_REF"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def revoke_substantiation_record_payload(
        revocation_reason: str = "certificate withdrawn by the issuing body",
        **overrides) -> Dict[str, Any]:
    payload = {"revocation_reason": revocation_reason}
    payload.update(overrides)
    return payload


def create_formula_payload(brief_id: str, **overrides) -> Dict[str, Any]:
    payload = {"brief_id": brief_id, "name": DEFAULTS["FORMULA_NAME"]}
    payload.update(overrides)
    return payload


def raw_material_component_payload(raw_material_id: str,
                                   weight_pct: float,
                                   **overrides) -> Dict[str, Any]:
    payload = {
        "component_type": "RAW_MATERIAL",
        "raw_material_id": raw_material_id,
        "weight_pct": weight_pct,
    }
    payload.update(overrides)
    return payload


def sub_formula_component_payload(sub_formula_id: str,
                                  weight_pct: float,
                                  **overrides) -> Dict[str, Any]:
    payload = {
        "component_type": "SUB_FORMULA",
        "sub_formula_id": sub_formula_id,
        "weight_pct": weight_pct,
    }
    payload.update(overrides)
    return payload


def formula_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_formula_revision_payload(name: str,
                                    expected_formula_version: int,
                                    **overrides) -> Dict[str, Any]:
    payload = {
        "name": name,
        "expected_formula_version": expected_formula_version,
    }
    payload.update(overrides)
    return payload


def brief_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def brief_clarification_payload(clarification_note: str, **overrides) -> Dict[str, Any]:
    payload = {"clarification_note": clarification_note}
    payload.update(overrides)
    return payload


def close_brief_payload(outcome: str,
                        loss_reason: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if loss_reason is not None:
        payload["loss_reason"] = loss_reason
    payload.update(overrides)
    return payload


def create_sample_lot_payload(formula_id: str,
                              batch_size_g: int = DEFAULTS["BATCH_SIZE_G"],
                              **overrides) -> Dict[str, Any]:
    payload = {"formula_id": formula_id, "batch_size_g": batch_size_g}
    payload.update(overrides)
    return payload


def lot_qc_payload(result: str, **overrides) -> Dict[str, Any]:
    payload = {"result": result}
    payload.update(overrides)
    return payload


def create_retention_cabinet_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "cabinet_code": DEFAULTS["CABINET_CODE"],
        "capacity_slots": DEFAULTS["CAPACITY_SLOTS"],
        "storage_temp_c": DEFAULTS["STORAGE_TEMP_C"],
    }
    payload.update(overrides)
    return payload


def create_retention_sample_payload(sample_lot_id: str,
                                    cabinet_id: str,
                                    quantity_g: int,
                                    stored_from: str,
                                    stored_until: str,
                                    **overrides) -> Dict[str, Any]:
    payload = {
        "sample_lot_id": sample_lot_id,
        "cabinet_id": cabinet_id,
        "quantity_g": quantity_g,
        "stored_from": stored_from,
        "stored_until": stored_until,
    }
    payload.update(overrides)
    return payload


def withdraw_retention_sample_payload(
        withdrawal_reason: str = "customer request", **overrides) -> Dict[str, Any]:
    payload = {"withdrawal_reason": withdrawal_reason}
    payload.update(overrides)
    return payload


def create_application_rig_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "rig_code": DEFAULTS["RIG_CODE"],
        "matrix_type": DEFAULTS["MATRIX_TYPE"],
        "cleanout_buffer_minutes": DEFAULTS["CLEANOUT_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_application_test_payload(sample_lot_id: str,
                                    rig_id: str,
                                    window_start: str,
                                    window_end: str,
                                    dosage_pct: float,
                                    consumed_g: int,
                                    **overrides) -> Dict[str, Any]:
    payload = {
        "sample_lot_id": sample_lot_id,
        "rig_id": rig_id,
        "window_start": window_start,
        "window_end": window_end,
        "dosage_pct": dosage_pct,
        "consumed_g": consumed_g,
    }
    payload.update(overrides)
    return payload


def application_test_result_payload(aroma_score: float,
                                    taste_score: float,
                                    stability_score: float,
                                    **overrides) -> Dict[str, Any]:
    payload = {
        "aroma_score": aroma_score,
        "taste_score": taste_score,
        "stability_score": stability_score,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(sample_lot_id: str,
                            shipped_g: int,
                            destination_country: str =
                            DEFAULTS["DESTINATION_COUNTRY"],
                            **overrides) -> Dict[str, Any]:
    payload = {
        "sample_lot_id": sample_lot_id,
        "destination_country": destination_country,
        "shipped_g": shipped_g,
    }
    payload.update(overrides)
    return payload


def dispatch_shipment_payload(tracking_reference: str = "TRK-0001",
                              **overrides) -> Dict[str, Any]:
    payload = {"tracking_reference": tracking_reference}
    payload.update(overrides)
    return payload


def cancel_shipment_payload(cancellation_reason: str = "customer hold",
                            **overrides) -> Dict[str, Any]:
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def create_scale_up_batch_payload(formula_id: str,
                                  target_kg: int = DEFAULTS["TARGET_KG"],
                                  **overrides) -> Dict[str, Any]:
    payload = {"formula_id": formula_id, "target_kg": target_kg}
    payload.update(overrides)
    return payload


def batch_pilot_run_payload(measured_yield_kg: float, **overrides) -> Dict[str, Any]:
    payload = {"measured_yield_kg": measured_yield_kg}
    payload.update(overrides)
    return payload


def batch_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_commercialization_forecast_payload(brief_id: str,
                                              annual_volume_kg: int,
                                              unit_price_cents_per_kg: int,
                                              expected_brief_version: int,
                                              **overrides) -> Dict[str, Any]:
    payload = {
        "brief_id": brief_id,
        "annual_volume_kg": annual_volume_kg,
        "unit_price_cents_per_kg": unit_price_cents_per_kg,
        "expected_brief_version": expected_brief_version,
    }
    payload.update(overrides)
    return payload


def create_disclosure_grant_payload(brief_id: str,
                                    formula_id: str,
                                    disclosed_tier: str,
                                    expires_at: str,
                                    redaction_level: str =
                                    DEFAULTS["REDACTION_LEVEL"],
                                    **overrides) -> Dict[str, Any]:
    payload = {
        "brief_id": brief_id,
        "formula_id": formula_id,
        "disclosed_tier": disclosed_tier,
        "redaction_level": redaction_level,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
