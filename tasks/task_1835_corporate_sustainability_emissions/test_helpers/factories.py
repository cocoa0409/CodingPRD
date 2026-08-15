"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS, year_window

_DEFAULT_FROM, _DEFAULT_TO = year_window(TEST_DEFAULTS["REPORTING_YEAR"])


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Plant",
        "country_code": TEST_DEFAULTS["COUNTRY_CODE"],
        "grid_region_code": TEST_DEFAULTS["GRID_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_emission_factor_payload(**overrides) -> dict:
    defaults = {
        "scope_category": "SCOPE1_STATIONARY",
        "region_code": "GLOBAL",
        "unit": "therm",
        "value_tco2e_per_unit": TEST_DEFAULTS["FUEL_FACTOR_VALUE"],
        "library_version": 1,
        "valid_from": _DEFAULT_FROM,
        "valid_to": _DEFAULT_TO,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": "FY2026",
        "reporting_year": TEST_DEFAULTS["REPORTING_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_activity_record_payload(cycle_id, site_id, factor_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "site_id": site_id,
        "factor_id": factor_id,
        "activity_type": "STATIONARY_FUEL",
        "quantity": 10,
        "unit": "therm",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "file_name": "invoice.pdf",
        "sha256_hex": "a" * 64,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "supplier_name": "Acme Steel",
        "category": "PURCHASED_GOODS",
        "spend_usd": 10000,
        "contact_user_id": "supplier-1",
        "due_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_target_payload(**overrides) -> dict:
    defaults = {
        "name": "50-by-2030",
        "base_year": 2025,
        "target_year": 2030,
        "reduction_pct": 50,
        "scope_coverage": "SCOPE1_2_3",
        "base_year_total_tco2e": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = {
        "registry": "M-RETS",
        "serial_number": "S-100",
        "technology": "SOLAR",
        "vintage_year": 2026,
        "quantity_mwh": 30,
    }
    defaults.update(overrides)
    return defaults


def create_questionnaire_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "framework": "CDP",
    }
    defaults.update(overrides)
    return defaults


# --- Action / transition payload helpers ---

def transition_payload(to_state, **extras) -> dict:
    payload = {"to_state": to_state}
    payload.update(extras)
    return payload


def answer_payload(section_key, answer_text) -> dict:
    return {"section_key": section_key, "answer_text": answer_text}


def respond_payload(supplier_tco2e) -> dict:
    return {"supplier_tco2e": supplier_tco2e}


def decision_payload(decision) -> dict:
    return {"decision": decision}


def review_decision_payload(decision, **extras) -> dict:
    payload = {"decision": decision}
    payload.update(extras)
    return payload


def retire_payload(cycle_id, site_id) -> dict:
    return {"cycle_id": cycle_id, "site_id": site_id}


def recalc_inventory_payload(expected_cycle_version) -> dict:
    return {"expected_cycle_version": expected_cycle_version}


def recalc_baseline_payload(base_cycle_id, expected_target_version) -> dict:
    return {"base_cycle_id": base_cycle_id, "expected_target_version": expected_target_version}


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def monthly_periods(year: int, count: int) -> list:
    """`count` adjacent non-overlapping monthly half-open periods starting in January."""
    periods = []
    for month in range(1, count + 1):
        start = f"{year}-{month:02d}-01T00:00:00Z"
        if month == 12:
            end = f"{year + 1}-01-01T00:00:00Z"
        else:
            end = f"{year}-{month + 1:02d}-01T00:00:00Z"
        periods.append((start, end))
    return periods


def sha256_hex(seed: int) -> str:
    """Distinct valid 64-char lowercase hex digests for evidence payloads."""
    return "%064x" % seed
