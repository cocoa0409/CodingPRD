"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Landlord",
    "ZIP_CODE": "90001",
    "ADDRESS": "1 Main St",
    "UNIT_LABEL": "Unit 1",
    "BEDROOM_COUNT": 1,
    "FAMILY_CODE": "FAM-1",
    "VOUCHER_BEDROOM_SIZE": 1,
    "ANNUAL_INCOME_CENTS": 2_400_000,
    "PAYMENT_STANDARD_CENTS": 150_000,
    "EFFECTIVE_FROM": "2026-01-01",
    "CONTRACT_RENT_CENTS": 150_000,
    "LEASE_START_DATE": "2026-08-01",
    "INSPECTION_TYPE": "ANNUAL",
    "SCHEDULED_DATE": "2026-08-05",
    "REPAIR_DESCRIPTION": "deficiency",
    "COMPARABLE_RENT_CENTS": 150_000,
    "SURVEY_DATE": "2026-06-01",
    "REQUESTED_RENT_CENTS": 160_000,
    "INCREASE_EFFECTIVE_DATE": "2027-08-01",
    "RECERT_DUE_DATE": "2027-08-01",
    "NEW_FAMILY_INCOME_CENTS": 3_000_000,
    "DESTINATION_ZIP": "90009",
    "ACTION_TYPE": "PORT_OUT",
}

_tax_id_counter = [0]


def _next_tax_id() -> str:
    _tax_id_counter[0] += 1
    return f"TAX-{_tax_id_counter[0]:06d}"


def create_landlord_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["LEGAL_NAME"], "tax_id": _next_tax_id()}
    defaults.update(overrides)
    return defaults


def create_property_payload(landlord_id: str, **overrides) -> dict:
    defaults = {
        "landlord_id": landlord_id,
        "address": DEFAULTS["ADDRESS"],
        "zip_code": DEFAULTS["ZIP_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_label": DEFAULTS["UNIT_LABEL"],
        "bedroom_count": DEFAULTS["BEDROOM_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_voucher_family_payload(**overrides) -> dict:
    defaults = {
        "family_code": DEFAULTS["FAMILY_CODE"],
        "voucher_bedroom_size": DEFAULTS["VOUCHER_BEDROOM_SIZE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_standard_payload(**overrides) -> dict:
    defaults = {
        "zip_code": DEFAULTS["ZIP_CODE"],
        "bedroom_count": DEFAULTS["BEDROOM_COUNT"],
        "amount_cents": DEFAULTS["PAYMENT_STANDARD_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_rent_comparable_payload(**overrides) -> dict:
    defaults = {
        "zip_code": DEFAULTS["ZIP_CODE"],
        "bedroom_count": DEFAULTS["BEDROOM_COUNT"],
        "rent_cents": DEFAULTS["COMPARABLE_RENT_CENTS"],
        "survey_date": DEFAULTS["SURVEY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(unit_id: str, family_id: str, expected_unit_version: int,
                            **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "family_id": family_id,
        "contract_rent_cents": DEFAULTS["CONTRACT_RENT_CENTS"],
        "lease_start_date": DEFAULTS["LEASE_START_DATE"],
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def schedule_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_type": DEFAULTS["INSPECTION_TYPE"],
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_repair_item_payload(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["REPAIR_DESCRIPTION"],
        "is_life_threatening": False,
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(outcome: str = "PASS") -> dict:
    return {"outcome": outcome}


def verify_item_payload(outcome: str = "PASS") -> dict:
    return {"outcome": outcome}


def create_rent_increase_request_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "requested_rent_cents": DEFAULTS["REQUESTED_RENT_CENTS"],
        "effective_date": DEFAULTS["INCREASE_EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_recertification_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "due_date": DEFAULTS["RECERT_DUE_DATE"],
        "new_family_income_cents": DEFAULTS["NEW_FAMILY_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def complete_recertification_payload(expected_contract_version: int) -> dict:
    return {"expected_contract_version": expected_contract_version}


def create_portability_action_payload(family_id: str, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "destination_zip": DEFAULTS["DESTINATION_ZIP"],
        "action_type": DEFAULTS["ACTION_TYPE"],
    }
    defaults.update(overrides)
    return defaults
