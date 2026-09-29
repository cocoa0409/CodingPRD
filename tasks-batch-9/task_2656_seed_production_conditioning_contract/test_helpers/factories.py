"""Request payload builders. Every factory carries input fields only."""

from __future__ import annotations

from typing import Any

from .constants import TEST_DEFAULTS


def create_variety_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "crop_kind": TEST_DEFAULTS["CROP_KIND"],
        "variety_name": TEST_DEFAULTS["VARIETY_NAME"],
        "max_seed_class": TEST_DEFAULTS["MAX_SEED_CLASS"],
        "isolation_min_m": TEST_DEFAULTS["ISOLATION_MIN_M"],
        "restricted_prior_crop_kinds": list(TEST_DEFAULTS["RESTRICTED_PRIOR_CROP_KINDS"]),
        "restricted_prior_crop_years": TEST_DEFAULTS["RESTRICTED_PRIOR_CROP_YEARS"],
        "germination_min_pct": TEST_DEFAULTS["GERMINATION_MIN_PCT"],
        "purity_min_pct": TEST_DEFAULTS["PURITY_MIN_PCT"],
        "max_off_type_per_10000": TEST_DEFAULTS["MAX_OFF_TYPE_PER_10000"],
        "max_restricted_weed_per_10000": TEST_DEFAULTS["MAX_RESTRICTED_WEED_PER_10000"],
        "max_disease_incidence_pct": TEST_DEFAULTS["MAX_DISEASE_INCIDENCE_PCT"],
        "max_rogueing_rounds": TEST_DEFAULTS["MAX_ROGUEING_ROUNDS"],
        "estimated_conditioning_shrink_pct": TEST_DEFAULTS["ESTIMATED_CONDITIONING_SHRINK_PCT"],
        "germ_validity_days": TEST_DEFAULTS["GERM_VALIDITY_DAYS"],
        "max_carryover_generations": TEST_DEFAULTS["MAX_CARRYOVER_GENERATIONS"],
        "treatment_required": False,
    }
    payload.update(overrides)
    return payload


def create_treatment_product_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_code": TEST_DEFAULTS["PRODUCT_CODE"],
        "epa_registration_number": TEST_DEFAULTS["EPA_REGISTRATION_NUMBER"],
        "allowed_crop_kinds": list(TEST_DEFAULTS["ALLOWED_CROP_KINDS"]),
        "max_rate_g_per_100kg": TEST_DEFAULTS["MAX_RATE_G_PER_100KG"],
        "requires_dye": True,
        "restricted_use": True,
        "label_signal_word": TEST_DEFAULTS["LABEL_SIGNAL_WORD"],
    }
    payload.update(overrides)
    return payload


def create_grower_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "grower_name": TEST_DEFAULTS["GROWER_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "contact_email": TEST_DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_production_field_payload(grower_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "grower_id": grower_id,
        "field_code": TEST_DEFAULTS["FIELD_CODE"],
        "acres": TEST_DEFAULTS["ACRES"],
        "isolation_distance_m": TEST_DEFAULTS["ISOLATION_DISTANCE_M"],
    }
    payload.update(overrides)
    return payload


def create_field_history_record_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "crop_kind": TEST_DEFAULTS["HISTORY_CROP_KIND"],
        "crop_year": TEST_DEFAULTS["HISTORY_CROP_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_eligibility_assessment_payload(variety_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "variety_id": variety_id,
        "season_year": TEST_DEFAULTS["SEASON_YEAR"],
        "seed_class": TEST_DEFAULTS["SEED_CLASS"],
    }
    payload.update(overrides)
    return payload


def create_production_contract_payload(
    grower_id: str, variety_id: str, production_field_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "grower_id": grower_id,
        "variety_id": variety_id,
        "production_field_id": production_field_id,
        "season_year": TEST_DEFAULTS["SEASON_YEAR"],
        "seed_class": TEST_DEFAULTS["SEED_CLASS"],
        "contracted_acres": TEST_DEFAULTS["CONTRACTED_ACRES"],
        "base_price_per_unit_cents": TEST_DEFAULTS["BASE_PRICE_PER_UNIT_CENTS"],
        "conditioning_charge_per_unit_cents": TEST_DEFAULTS["CONDITIONING_CHARGE_PER_UNIT_CENTS"],
        "advance_total_cents": TEST_DEFAULTS["ADVANCE_TOTAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def sign_contract_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"planted_on": TEST_DEFAULTS["PLANTED_ON"]}
    payload.update(overrides)
    return payload


def cancel_contract_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"cancel_reason": "Grower withdrew from the program"}
    payload.update(overrides)
    return payload


def create_field_inspection_payload(production_contract_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "production_contract_id": production_contract_id,
        "inspected_on": TEST_DEFAULTS["INSPECTED_ON"],
        "sampled_plants": TEST_DEFAULTS["SAMPLED_PLANTS"],
        "off_type_plants": TEST_DEFAULTS["OFF_TYPE_PLANTS"],
        "restricted_weed_plants": TEST_DEFAULTS["RESTRICTED_WEED_PLANTS"],
        "diseased_plants": TEST_DEFAULTS["DISEASED_PLANTS"],
        "isolation_verified_m": TEST_DEFAULTS["ISOLATION_VERIFIED_M"],
    }
    payload.update(overrides)
    return payload


def rogueing_declaration_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rogueing_plants_removed": 10,
        "rogueing_declared_on": "2026-08-25",
    }
    payload.update(overrides)
    return payload


def rogueing_verification_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"verified_remaining_off_type_plants": 8}
    payload.update(overrides)
    return payload


def create_harvest_equipment_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "equipment_code": TEST_DEFAULTS["EQUIPMENT_CODE"],
        "equipment_kind": TEST_DEFAULTS["EQUIPMENT_KIND"],
        "cleanout_minutes_required": TEST_DEFAULTS["EQUIPMENT_CLEANOUT_MINUTES_REQUIRED"],
    }
    payload.update(overrides)
    return payload


def cleanout_certification_payload(variety_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "variety_id": variety_id,
        "cleaned_at": TEST_DEFAULTS["CLEANED_AT"],
    }
    payload.update(overrides)
    return payload


def create_harvest_event_payload(
    production_contract_id: str, harvest_equipment_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "production_contract_id": production_contract_id,
        "harvest_equipment_id": harvest_equipment_id,
        "window_start": TEST_DEFAULTS["HARVEST_WINDOW_START"],
        "window_end": TEST_DEFAULTS["HARVEST_WINDOW_END"],
        "gross_weight_kg": TEST_DEFAULTS["GROSS_WEIGHT_KG"],
        "moisture_pct": TEST_DEFAULTS["MOISTURE_PCT"],
        "bag_size_kg": TEST_DEFAULTS["BAG_SIZE_KG"],
    }
    payload.update(overrides)
    return payload


def create_conditioning_line_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "line_code": TEST_DEFAULTS["LINE_CODE"],
        "cleanout_minutes_required": TEST_DEFAULTS["LINE_CLEANOUT_MINUTES_REQUIRED"],
        "capacity_kg_per_hour": TEST_DEFAULTS["CAPACITY_KG_PER_HOUR"],
    }
    payload.update(overrides)
    return payload


def create_conditioning_run_payload(
    seed_lot_id: str, conditioning_line_id: str, stage: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "seed_lot_id": seed_lot_id,
        "conditioning_line_id": conditioning_line_id,
        "stage": stage,
        "window_start": TEST_DEFAULTS["CLEANING_WINDOW_START"],
        "window_end": TEST_DEFAULTS["CLEANING_WINDOW_END"],
        "input_kg": TEST_DEFAULTS["GROSS_WEIGHT_KG"],
    }
    payload.update(overrides)
    return payload


def complete_conditioning_run_payload(output_kg: float, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"output_kg": output_kg}
    payload.update(overrides)
    return payload


def reverse_conditioning_run_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"reversal_reason": "Bagging line miscount, rebagging required"}
    payload.update(overrides)
    return payload


def create_carryover_payload(expected_seed_lot_version: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "expected_seed_lot_version": expected_seed_lot_version,
        "next_season_year": TEST_DEFAULTS["SEASON_YEAR"] + 1,
    }
    payload.update(overrides)
    return payload


def create_lot_sample_payload(seed_lot_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "seed_lot_id": seed_lot_id,
        "sample_kind": "INITIAL",
        "sampled_on": TEST_DEFAULTS["SAMPLED_ON"],
    }
    payload.update(overrides)
    return payload


def lot_sample_results_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "germination_pct": TEST_DEFAULTS["RESULT_GERMINATION_PCT"],
        "purity_pct": TEST_DEFAULTS["RESULT_PURITY_PCT"],
        "inert_pct": TEST_DEFAULTS["RESULT_INERT_PCT"],
        "weed_seed_count_per_kg": TEST_DEFAULTS["RESULT_WEED_SEED_COUNT_PER_KG"],
        "tested_at": TEST_DEFAULTS["TESTED_AT"],
    }
    payload.update(overrides)
    return payload


def create_certification_tag_payload(seed_lot_id: str, lot_sample_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "seed_lot_id": seed_lot_id,
        "lot_sample_id": lot_sample_id,
        "tag_class": TEST_DEFAULTS["TAG_CLASS"],
        "bag_count": TEST_DEFAULTS["TAG_BAG_COUNT"],
    }
    payload.update(overrides)
    return payload


def void_certification_tag_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"void_reason": "Tag block damaged in transit"}
    payload.update(overrides)
    return payload


def create_settlement_payload(
    production_contract_id: str, expected_contract_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "production_contract_id": production_contract_id,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def dispute_settlement_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"dispute_reason": "Grower disputes the conditioning charge basis"}
    payload.update(overrides)
    return payload


def pay_settlement_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"payment_reference": TEST_DEFAULTS["PAYMENT_REFERENCE"]}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def treatment_label_text(
    epa_registration_number: str = TEST_DEFAULTS["EPA_REGISTRATION_NUMBER"],
    signal_word: str = TEST_DEFAULTS["LABEL_SIGNAL_WORD"],
    include_dyed: bool = True,
) -> str:
    """Build a treated-seed label containing every mandated disclosure."""
    parts = [f"EPA Reg. No. {epa_registration_number}"]
    if include_dyed:
        parts.append("DYED")
    if signal_word:
        parts.append(signal_word)
    parts.append("Treated seed - do not use for food, feed or oil purposes.")
    return " | ".join(parts)
