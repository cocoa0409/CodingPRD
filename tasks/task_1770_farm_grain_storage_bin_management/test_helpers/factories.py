"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BIN_NAME": "BIN-1",
    "BIN_CAPACITY_BU": 5000.00,
    "CROP": "CORN",
    "GRADE": "GRADE_1",
    "FILL_DATE": "2026-08-01T00:00:00Z",
    "ORIGINAL_BU": 1000.00,
    "FILL_MOISTURE_PCT": 15.0,
    "FILL_BASIS_CENTS": -25,
    "REF_PRICE_CENTS_PER_BU": 430,
    "AMBIENT_TEMP_F": 60.0,
    "CONTRACTED_BU": 2000.00,
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-12-31T23:59:59Z",
    "BASIS_CENTS_PER_BU": -20,
    "FUTURES_REF_CENTS_PER_BU": 450,
    "SCHEDULED_START": "2026-08-10T08:00:00Z",
    "SCHEDULED_END": "2026-08-10T12:00:00Z",
    "PLANNED_BU": 100.00,
    "APPLICATOR_NAME": "Alice A",
    "LICENSE_NO": "LIC-A",
    "CERT_EXPIRES_AT": "2027-06-01T00:00:00Z",
    "COVERAGE_LIMIT_CENTS": 1_000_000,
    "DEDUCTIBLE_CENTS": 5_000,
    "PERIOD_START": "2026-07-01T00:00:00Z",
    "PERIOD_END": "2026-12-31T23:59:59Z",
    "PLANNED_START": "2026-08-02T08:00:00Z",
    "PLANNED_END": "2026-08-02T10:00:00Z",
    "APP_START": "2026-08-01T00:00:00Z",
    "APP_END": "2026-08-01T06:00:00Z",
}


def create_bin_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BIN_NAME"],
        "capacity_bu": DEFAULTS["BIN_CAPACITY_BU"],
        "crop": DEFAULTS["CROP"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(bin_id, **overrides) -> dict:
    defaults = {
        "bin_id": bin_id,
        "crop": DEFAULTS["CROP"],
        "grade": DEFAULTS["GRADE"],
        "fill_date": DEFAULTS["FILL_DATE"],
        "original_bu": DEFAULTS["ORIGINAL_BU"],
        "fill_moisture_pct": DEFAULTS["FILL_MOISTURE_PCT"],
        "fill_basis_cents": DEFAULTS["FILL_BASIS_CENTS"],
        "reference_price_cents_per_bu": DEFAULTS["REF_PRICE_CENTS_PER_BU"],
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(bin_id, **overrides) -> dict:
    defaults = {
        "bin_id": bin_id,
        "recorded_at": "2026-08-05T10:00:00Z",
        "ambient_temp_f": DEFAULTS["AMBIENT_TEMP_F"],
        "cable_temps_f": [90.0],
        "insect_activity": False,
    }
    defaults.update(overrides)
    return defaults


def create_fumigation_payload(bin_id, applicator_id, **overrides) -> dict:
    defaults = {
        "bin_id": bin_id,
        "applicator_id": applicator_id,
        "product": "PHOSPHINE",
        "application_start": DEFAULTS["APP_START"],
        "application_end": DEFAULTS["APP_END"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(bin_id, **overrides) -> dict:
    defaults = {
        "bin_id": bin_id,
        "planned_start": DEFAULTS["PLANNED_START"],
        "planned_end": DEFAULTS["PLANNED_END"],
        "atmosphere_test_passed": True,
        "loto_confirmed": True,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "crop": DEFAULTS["CROP"],
        "contracted_bu": DEFAULTS["CONTRACTED_BU"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "basis_cents_per_bu": DEFAULTS["BASIS_CENTS_PER_BU"],
        "futures_ref_cents_per_bu": DEFAULTS["FUTURES_REF_CENTS_PER_BU"],
    }
    defaults.update(overrides)
    return defaults


def create_loadout_payload(contract_id, bin_id, expected_contract_version, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "bin_id": bin_id,
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
        "planned_bu": DEFAULTS["PLANNED_BU"],
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "crop": DEFAULTS["CROP"],
        "coverage_limit_cents": DEFAULTS["COVERAGE_LIMIT_CENTS"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
        "valuation_clause": "SPOT",
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id, spoilage_alert_id, **overrides) -> dict:
    defaults = {"policy_id": policy_id, "spoilage_alert_id": spoilage_alert_id}
    defaults.update(overrides)
    return defaults


def create_applicator_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["APPLICATOR_NAME"],
        "license_no": DEFAULTS["LICENSE_NO"],
        "cert_expires_at": DEFAULTS["CERT_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def deliver_payload(**overrides) -> dict:
    defaults = {
        "delivered_at": "2026-08-10T10:00:00Z",
        "scale_tickets": [
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0}
        ],
    }
    defaults.update(overrides)
    return defaults
