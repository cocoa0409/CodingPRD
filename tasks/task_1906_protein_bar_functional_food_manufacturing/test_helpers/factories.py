"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "SUPPLIER_NAME": "Test Supplier",
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_EMAIL": "customer@example.com",
    "FORMULA_NAME": "Test Formula",
    "BAR_WEIGHT_G": 60,
    "BATCH_SIZE_KG": 100,
    "TARGET_PROTEIN_G": 15,
    "LINE_NAME": "L1",
    "CAPACITY_KG_PER_HOUR": 500,
    "SLAB_WEIGHT_KG": 20,
    "MOQ_CASES": 100,
    "COMMITTED_CASES": 300,
    "RATE_CENTS": 500,
    "QUARTER_START": "2026-07-01T00:00:00Z",
    "RECEIVED_AT": "2026-08-01T00:00:00Z",
    "CHAMBER_ID": "CH1",
    "SHELF_POSITION": "P1",
    "STUDY_START": "2026-08-01T00:00:00Z",
    "STUDY_EXPIRY": "2026-10-30T00:00:00Z",
    "HARDNESS_LIMIT_N": 200.0,
    "BIN_ID": "BIN-1",
}


def create_supplier_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["SUPPLIER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_ingredient_payload(**overrides) -> dict:
    defaults = {"name": "ING", "category": "BINDER"}
    defaults.update(overrides)
    return defaults


def create_ingredient_lot_payload(**overrides) -> dict:
    defaults = {
        "ingredient_id": None,
        "supplier_id": None,
        "lot_code": "LOT-1",
        "received_qty_kg": 100,
        "received_at": DEFAULTS["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "contact_email": DEFAULTS["CUSTOMER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def default_tier_breaks():
    return [
        {
            "upto_cases": 999999999,
            "rate_cents_per_case": DEFAULTS["RATE_CENTS"],
        }
    ]


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "pricing_mode": "MARGINAL",
        "moq_cases_per_run": DEFAULTS["MOQ_CASES"],
        "committed_cases_per_quarter": DEFAULTS["COMMITTED_CASES"],
        "tier_breaks": default_tier_breaks(),
        "quarter_start": DEFAULTS["QUARTER_START"],
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "name": DEFAULTS["FORMULA_NAME"],
        "bar_weight_g": DEFAULTS["BAR_WEIGHT_G"],
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(**overrides) -> dict:
    defaults = {
        "ingredient_lines": [],
        "batch_size_kg": DEFAULTS["BATCH_SIZE_KG"],
        "target_protein_g_per_serving": DEFAULTS["TARGET_PROTEIN_G"],
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LINE_NAME"],
        "capacity_kg_per_hour": DEFAULTS["CAPACITY_KG_PER_HOUR"],
        "slab_weight_kg": DEFAULTS["SLAB_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(**overrides) -> dict:
    defaults = {
        "revision_id": None,
        "agreement_id": None,
        "line_id": None,
        "planned_cases": 100,
        "expected_agreement_version": None,
    }
    defaults.update(overrides)
    return defaults


def schedule_run_payload(**overrides) -> dict:
    defaults = {
        "start_utc": "2026-08-06T08:00:00Z",
        "end_utc": "2026-08-06T10:00:00Z",
        "expected_line_version": None,
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(**overrides) -> dict:
    defaults = {"produced_cases": 100, "scrapped_cases": 0}
    defaults.update(overrides)
    return defaults


def create_retain_sample_payload(**overrides) -> dict:
    defaults = {
        "bin_id": DEFAULTS["BIN_ID"],
        "cases_count": 1,
        "retain_until_utc": "2026-09-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_study_payload(**overrides) -> dict:
    defaults = {
        "revision_id": None,
        "chamber_id": DEFAULTS["CHAMBER_ID"],
        "shelf_position": DEFAULTS["SHELF_POSITION"],
        "start_utc": DEFAULTS["STUDY_START"],
        "expiry_utc": DEFAULTS["STUDY_EXPIRY"],
        "hardness_limit_n": DEFAULTS["HARDNESS_LIMIT_N"],
    }
    defaults.update(overrides)
    return defaults


def record_pull_payload(**overrides) -> dict:
    defaults = {"hardness_n": 50.0, "recorded_utc": "2026-08-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_claim_review_payload(**overrides) -> dict:
    defaults = {
        "revision_id": None,
        "claim_tag": "HIGH_PROTEIN",
        "claim_type": "NUTRIENT_CONTENT",
    }
    defaults.update(overrides)
    return defaults
