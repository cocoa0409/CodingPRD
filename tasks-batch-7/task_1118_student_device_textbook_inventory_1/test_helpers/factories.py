"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROGRAM_NAME": "OneToOne-2026",
    "SCHOOL_YEAR": "2026-2027",
    "FLEET_NAME": "Chromebook-Grade-9-2026",
    "ASSET_CLASS": "DEVICE",
    "REPLACEMENT_COST_CENTS": 100000,
    "SALVAGE_VALUE_CENTS": 10000,
    "USEFUL_LIFE_MONTHS": 36,
    "IN_SERVICE_DATE": "2025-09-01T00:00:00Z",
    "GRADE_LEVEL": 9,
    "AUP_VERSION": "AUP-2026.v3",
    "GUARDIAN_NAME": "Guardian One",
    "PREMIUM_CENTS": 5000,
    "DEDUCTIBLE_CENTS": 2500,
    "COVERAGE_CAP_CENTS": 50000,
    "EXPECTED_RETURN_DATE": "2027-06-01T00:00:00Z",
    "MAX_LOANER_DAYS": 14,
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "school_year": DEFAULTS["SCHOOL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_fleet_payload(**overrides) -> dict:
    defaults = {
        "fleet_name": DEFAULTS["FLEET_NAME"],
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "unit_replacement_cost_cents": DEFAULTS["REPLACEMENT_COST_CENTS"],
        "salvage_value_cents": DEFAULTS["SALVAGE_VALUE_CENTS"],
        "useful_life_months": DEFAULTS["USEFUL_LIFE_MONTHS"],
        "in_service_date": DEFAULTS["IN_SERVICE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_unit_payload(barcode="BC-0001", serial="SN-0001", **overrides) -> dict:
    defaults = {
        "asset_tag_barcode": barcode,
        "serial_number": serial,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(external_id="SIS-0001", full_name="Test Student",
                           **overrides) -> dict:
    defaults = {
        "student_external_id": external_id,
        "full_name": full_name,
        "grade_level": DEFAULTS["GRADE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def sign_agreement_payload(**overrides) -> dict:
    defaults = {
        "acceptable_use_version": DEFAULTS["AUP_VERSION"],
        "signed_by_guardian_name": DEFAULTS["GUARDIAN_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "premium_cents": DEFAULTS["PREMIUM_CENTS"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
        "coverage_cap_cents": DEFAULTS["COVERAGE_CAP_CENTS"],
        "academic_year": DEFAULTS["SCHOOL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(asset_unit_id, expected_student_version, **overrides) -> dict:
    defaults = {
        "asset_unit_id": asset_unit_id,
        "expected_return_date": DEFAULTS["EXPECTED_RETURN_DATE"],
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def return_assignment_payload(**overrides) -> dict:
    defaults = {"return_condition_grade": "A"}
    defaults.update(overrides)
    return defaults


def create_damage_report_payload(**overrides) -> dict:
    defaults = {
        "damage_category": "COSMETIC",
        "observed_condition_grade": "A",
    }
    defaults.update(overrides)
    return defaults


def settle_fee_payload(payment_cents, **overrides) -> dict:
    defaults = {"payment_cents": payment_cents}
    defaults.update(overrides)
    return defaults


def create_loaner_checkout_payload(**overrides) -> dict:
    defaults = {"checkout_reason": "REPAIR"}
    defaults.update(overrides)
    return defaults


def create_audit_sweep_payload(expected_program_version, **overrides) -> dict:
    defaults = {
        "sweep_label": "spring-2026-cycle-2",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def complete_repair_payload(**overrides) -> dict:
    defaults = {"repair_cost_cents": 15000, "post_repair_grade": "B"}
    defaults.update(overrides)
    return defaults
