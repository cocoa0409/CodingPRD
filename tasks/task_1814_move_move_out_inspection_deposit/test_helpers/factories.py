"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "JURISDICTION_CODE": "CA-ACT",
    "DEADLINE_DAYS": 21,
    "DISPUTE_WINDOW_DAYS": 30,
    "INTEREST_RATE_BP": 300,
    "STALE_CHECK_DAYS": 180,
    "SMALL_CLAIMS_CAP_CENTS": 1_000_000,
    "BAD_FAITH_MULTIPLIER": 2,
    "PROPERTY_NAME": "Maple Court",
    "PROPERTY_ADDRESS": "1 Maple St",
    "KEY_CHARGE_CENTS": 5_000,
    "FOB_CHARGE_CENTS": 7_500,
    "LOCK_CHANGE_CENTS": 12_000,
    "UNIT_NUMBER": "1A",
    "CARPET_INSTALLED_ON": "2022-08-01",
    "CARPET_LIFE_YEARS": 5,
    "PAINT_APPLIED_ON": "2025-08-01",
    "PAINT_LIFE_YEARS": 3,
    "TENANT_NAME": "Tanya Tenant",
    "LEASE_START_ON": "2025-01-10",
    "LEASE_END_ON": "2026-08-10",
    "MONTHLY_RENT_CENTS": 150_000,
    "DEPOSIT_CENTS": 200_000,
    "KEYS_ISSUED": 2,
    "FOBS_ISSUED": 1,
    "INSPECTOR_USER_ID": "insp-1",
    "MOVE_IN_START": "2025-01-10T09:00:00Z",
    "MOVE_IN_END": "2025-01-10T10:00:00Z",
    "MOVE_OUT_START": "2026-08-01T10:00:00Z",
    "MOVE_OUT_END": "2026-08-01T11:00:00Z",
    "PAYEE_NAME": "Tanya Tenant",
}


def create_jurisdiction_profile_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["JURISDICTION_CODE"],
        "deposit_return_deadline_days": DEFAULTS["DEADLINE_DAYS"],
        "dispute_window_days": DEFAULTS["DISPUTE_WINDOW_DAYS"],
        "interest_required": True,
        "annual_interest_rate_bp": DEFAULTS["INTEREST_RATE_BP"],
        "interest_basis": "ACTUAL_DAYS",
        "stale_check_days": DEFAULTS["STALE_CHECK_DAYS"],
        "small_claims_cap_cents": DEFAULTS["SMALL_CLAIMS_CAP_CENTS"],
        "bad_faith_multiplier": DEFAULTS["BAD_FAITH_MULTIPLIER"],
        "lock_change_allowed": True,
        "allow_actual_cost_charge": False,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROPERTY_NAME"],
        "address": DEFAULTS["PROPERTY_ADDRESS"],
        "jurisdiction_profile_id": None,
        "key_charge_cents": DEFAULTS["KEY_CHARGE_CENTS"],
        "fob_charge_cents": DEFAULTS["FOB_CHARGE_CENTS"],
        "lock_change_cents": DEFAULTS["LOCK_CHANGE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "property_id": None,
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "carpet_installed_on": DEFAULTS["CARPET_INSTALLED_ON"],
        "carpet_life_years": DEFAULTS["CARPET_LIFE_YEARS"],
        "paint_applied_on": DEFAULTS["PAINT_APPLIED_ON"],
        "paint_life_years": DEFAULTS["PAINT_LIFE_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_tenancy_payload(**overrides) -> dict:
    defaults = {
        "unit_id": None,
        "tenant_display_name": DEFAULTS["TENANT_NAME"],
        "lease_start_on": DEFAULTS["LEASE_START_ON"],
        "lease_end_on": DEFAULTS["LEASE_END_ON"],
        "monthly_rent_cents": DEFAULTS["MONTHLY_RENT_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "keys_issued": DEFAULTS["KEYS_ISSUED"],
        "fobs_issued": DEFAULTS["FOBS_ISSUED"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "tenancy_id": None,
        "kind": "MOVE_IN",
        "inspector_user_id": DEFAULTS["INSPECTOR_USER_ID"],
        "scheduled_start_at": DEFAULTS["MOVE_IN_START"],
        "scheduled_end_at": DEFAULTS["MOVE_IN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_item_payload(**overrides) -> dict:
    defaults = {
        "area_name": "bedroom_paint",
        "category": "PAINT",
        "condition": "GOOD",
        "photo_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_deduction_payload(**overrides) -> dict:
    defaults = {
        "tenancy_id": None,
        "source": "CLEANING",
        "description": "oven cleaning",
        "amount_cents": 8_000,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    defaults = {
        "tenancy_id": None,
        "expected_tenancy_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "statement_id": None,
        "disputed_amount_cents": 20_000,
        "reason": "paint was already worn",
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "tenancy_id": None,
        "statement_id": None,
        "kind": "REFUND",
        "amount_cents": None,
        "payee_name": DEFAULTS["PAYEE_NAME"],
    }
    defaults.update(overrides)
    return defaults
