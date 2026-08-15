"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CONTRACTOR_NAME": "Test Electric",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "JOB_NAME": "Test Job",
    "JOBSITE_ADDRESS": "1 Site Rd",
    "VALID_UNTIL": "2027-01-01",
    "REASON": "lead time",
    "DECISION": "APPROVE",
    "TRUCK_ID": "T1",
    "DELIVERY_DATE": "2026-08-10",
    "WINDOW_START_HOUR": 8,
    "WINDOW_END_HOUR": 12,
}


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CONTRACTOR_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_catalog_item_payload(**overrides) -> dict:
    """EA item by default; pass sell_uom="FOOT" plus the three reel fields
    for by-the-foot material. `sku` is required by the PRD (section 3.2) and
    has no default here so required-field tests can genuinely omit it; every
    happy-path caller passes sku explicitly."""
    defaults = {
        "manufacturer_name": "SquareD",
        "sell_uom": "EA",
        "list_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_job_account_payload(**overrides) -> dict:
    defaults = {
        "contractor_id": None,
        "job_name": DEFAULTS["JOB_NAME"],
        "jobsite_address": DEFAULTS["JOBSITE_ADDRESS"],
        "pricing_mode": "FIRM_PRICE",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_quote_payload(**overrides) -> dict:
    defaults = {
        "job_account_id": None,
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(**overrides) -> dict:
    defaults = {
        "quote_id": None,
        "catalog_item_id": None,
        "qty": 1,
        "unit_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_substitution_request_payload(**overrides) -> dict:
    defaults = {
        "quote_line_id": None,
        "proposed_item_id": None,
        "reason": DEFAULTS["REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {"decision": DEFAULTS["DECISION"]}
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    defaults = {
        "job_account_id": None,
        "quote_id": None,
        "expected_job_account_version": None,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_stock_receipt_payload(**overrides) -> dict:
    defaults = {"qty": 1}
    defaults.update(overrides)
    return defaults


def create_lien_waiver_payload(**overrides) -> dict:
    defaults = {"expires_on": "2027-01-01"}
    defaults.update(overrides)
    return defaults


def create_schedule_payload(**overrides) -> dict:
    defaults = {
        "truck_id": DEFAULTS["TRUCK_ID"],
        "delivery_date": DEFAULTS["DELIVERY_DATE"],
        "window_start_hour": DEFAULTS["WINDOW_START_HOUR"],
        "window_end_hour": DEFAULTS["WINDOW_END_HOUR"],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_program_payload(**overrides) -> dict:
    defaults = {
        "manufacturer_name": "Southwire",
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
        "tiers": [{"threshold_cents": 0, "rebate_pct": 0.05}],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_claim_payload(**overrides) -> dict:
    defaults = {"rebate_program_id": None}
    defaults.update(overrides)
    return defaults


def create_clock_payload(**overrides) -> dict:
    defaults = {"to_iso8601": "2026-08-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_index_reading_payload(**overrides) -> dict:
    defaults = {"month": "2026-08", "index_value": 100.0}
    defaults.update(overrides)
    return defaults
