"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "PROTOCOL_NUMBER": "P-0001",
    "TITLE": "Test Study",
    "PHASE": "PHASE_II",
    "BLINDING_MODEL": "DOUBLE_BLIND",
    "MAX_DOSE_PER_VISIT_MG": 200,
    "SUSPENSION_THRESHOLD_PCT": 10,
    "SITE_NUMBER": "S1",
    "SITE_NAME": "Site One",
    "PRINCIPAL_INVESTIGATOR": "Dr A",
    "FULL_NAME": "Pharm One",
    "LICENSE_NUMBER": "L-0001",
    "LOT_NUMBER": "LOT-0001",
    "PRODUCT_NAME": "DrugX",
    "STRENGTH_MG": 50,
    "DOSAGE_FORM": "VIAL",
    "EXPIRY_DATE": "2027-06-01T00:00:00Z",
    "STORAGE_MIN_C": 2,
    "STORAGE_MAX_C": 8,
    "STABILITY_BUDGET_MINUTES": 600,
    "UNITS_PER_KIT": 10,
    "STRATUM": "STANDARD",
    "MONITOR_NAME": "CRA Jo",
    # Default fee schedule: neutral zeros except monitoring rate (PRD §3.1).
    "SETUP_FEE_CENTS": 0,
    "DISPENSING_FEE_CENTS": 5000,
    "DISPENSING_TIER_THRESHOLD": 2,
    "DISPENSING_TIER_FEE_CENTS": 3000,
    "MONITORING_FEE_CENTS_PER_HOUR": 10000,
    "STORAGE_FEE_CENTS_PER_KIT_MONTH": 100,
    "UNBLINDING_FEE_CENTS": 25000,
    "OVERHEAD_PCT": 0,
}


def create_study_payload(**overrides) -> dict:
    defaults = {
        "protocol_number": DEFAULTS["PROTOCOL_NUMBER"],
        "title": DEFAULTS["TITLE"],
        "phase": DEFAULTS["PHASE"],
        "blinding_model": DEFAULTS["BLINDING_MODEL"],
        "max_dose_per_visit_mg": DEFAULTS["MAX_DOSE_PER_VISIT_MG"],
        "unblinding_suspension_threshold_pct": DEFAULTS["SUSPENSION_THRESHOLD_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "site_number": DEFAULTS["SITE_NUMBER"],
        "name": DEFAULTS["SITE_NAME"],
        "principal_investigator": DEFAULTS["PRINCIPAL_INVESTIGATOR"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "full_name": DEFAULTS["FULL_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "lot_number": DEFAULTS["LOT_NUMBER"],
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "strength_mg": DEFAULTS["STRENGTH_MG"],
        "dosage_form": DEFAULTS["DOSAGE_FORM"],
        "expiry_date": DEFAULTS["EXPIRY_DATE"],
        "storage_temp_min_celsius": DEFAULTS["STORAGE_MIN_C"],
        "storage_temp_max_celsius": DEFAULTS["STORAGE_MAX_C"],
        "stability_budget_minutes": DEFAULTS["STABILITY_BUDGET_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(lot_id, site_id, kit_numbers, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "site_id": site_id,
        "kit_numbers": list(kit_numbers),
        "units_per_kit": DEFAULTS["UNITS_PER_KIT"],
    }
    defaults.update(overrides)
    return defaults


def create_subject_payload(site_id, subject_number, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "subject_number": subject_number,
        "stratum": DEFAULTS["STRATUM"],
    }
    defaults.update(overrides)
    return defaults


def slot_spec(sequence_number, kit_number, stratum=DEFAULTS["STRATUM"], arm_code="TRT-A") -> dict:
    return {
        "sequence_number": sequence_number,
        "stratum": stratum,
        "kit_number": kit_number,
        "arm_code": arm_code,
    }


def replace_slots_payload(slots, expected_study_version) -> dict:
    return {"slots": list(slots), "expected_study_version": expected_study_version}


def create_dispensing_payload(subject_id, kit_id, visit_number, quantity_dispensed) -> dict:
    return {
        "subject_id": subject_id,
        "kit_id": kit_id,
        "visit_number": visit_number,
        "quantity_dispensed": quantity_dispensed,
    }


def create_return_payload(dispensing_record_id, quantity_returned) -> dict:
    return {
        "dispensing_record_id": dispensing_record_id,
        "quantity_returned": quantity_returned,
    }


def create_destruction_payload(kit_id, site_id, witness_staff_id, quantity_destroyed,
                               window_start="2026-08-20T10:00:00Z",
                               window_end="2026-08-20T11:00:00Z",
                               method="INCINERATION") -> dict:
    return {
        "kit_id": kit_id,
        "site_id": site_id,
        "method": method,
        "facility_window_start": window_start,
        "facility_window_end": window_end,
        "quantity_destroyed": quantity_destroyed,
        "witness_staff_id": witness_staff_id,
    }


def create_unblinding_payload(subject_id, reason="Suspected SAE") -> dict:
    return {"subject_id": subject_id, "reason": reason}


def create_monitor_visit_payload(site_id, scheduled_start, scheduled_end,
                                 monitor_name=DEFAULTS["MONITOR_NAME"]) -> dict:
    return {
        "site_id": site_id,
        "monitor_name": monitor_name,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def create_temperature_log_payload(site_id, celsius, source="DATALOGGER") -> dict:
    return {"site_id": site_id, "celsius": celsius, "source": source}


def create_fee_schedule_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "setup_fee_cents": DEFAULTS["SETUP_FEE_CENTS"],
        "dispensing_fee_cents": DEFAULTS["DISPENSING_FEE_CENTS"],
        "dispensing_tier_threshold": DEFAULTS["DISPENSING_TIER_THRESHOLD"],
        "dispensing_tier_fee_cents": DEFAULTS["DISPENSING_TIER_FEE_CENTS"],
        "monitoring_fee_cents_per_hour": DEFAULTS["MONITORING_FEE_CENTS_PER_HOUR"],
        "storage_fee_cents_per_kit_month": DEFAULTS["STORAGE_FEE_CENTS_PER_KIT_MONTH"],
        "unblinding_fee_cents": DEFAULTS["UNBLINDING_FEE_CENTS"],
        "overhead_pct": DEFAULTS["OVERHEAD_PCT"],
    }
    defaults.update(overrides)
    return defaults
