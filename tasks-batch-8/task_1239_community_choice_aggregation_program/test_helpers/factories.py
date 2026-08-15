"""Payload factories — one per entity, input fields only (PRD §4)."""
from .constants import TEST_DEFAULTS, CLOCK_BOOT


def create_authority_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Valley Clean Alliance",
        "utility_territory_code": "PGE",
        "er_balancing_authority": "CISO",
        "rate_setting_policy": "COST_PLUS",
        "rps_target_pct": TEST_DEFAULTS["RPS_TARGET_PCT"],
        "bad_debt_trueup_cap_pct": TEST_DEFAULTS["BAD_DEBT_TRUEUP_CAP_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_account_spec(**overrides) -> dict:
    """One account entry for the bulk ingest payload."""
    defaults = {
        "utility_account_number": "U-0001",
        "service_class": "RESIDENTIAL",
        "annual_kwh_estimate": 12000,
        "annual_peak_kw": 4.0,
        "da_eligible": False,
    }
    defaults.update(overrides)
    return defaults


def create_ingest_payload(accounts) -> dict:
    return {"accounts": accounts}


def create_notice_payload(**overrides) -> dict:
    defaults = {
        "wave_label": "W1",
        "notice_mailed_on": CLOCK_BOOT,
        "target_service_classes": ["RESIDENTIAL"],
    }
    defaults.update(overrides)
    return defaults


def create_opt_out_request_payload(**overrides) -> dict:
    defaults = {
        "service_account_id": None,
        "enrollment_notice_id": None,
        "election_type": "OPT_OUT",
        "channel": "WEB",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": TEST_DEFAULTS["PRODUCT_CODE"],
        "election_key": "DEFAULT",
        "renewable_pct": 0.50,
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "energy_rate_cents_per_kwh": TEST_DEFAULTS["ENERGY_RATE_CENTS_PER_KWH"],
        "pcia_rate_cents_per_kwh": TEST_DEFAULTS["PCIA_RATE_CENTS_PER_KWH"],
        "incumbent_benchmark_rate_cents_per_kwh": TEST_DEFAULTS[
            "INCUMBENT_BENCHMARK_CENTS_PER_KWH"
        ],
    }
    defaults.update(overrides)
    return defaults


def create_supply_contract_payload(**overrides) -> dict:
    defaults = {
        "counterparty": "Solaris Energy LLC",
        "contract_type": "PPA",
        "delivery_start": "2026-01-01T00:00:00Z",
        "delivery_end": "2027-01-01T00:00:00Z",
        "capacity_mw": 20.0,
        "total_mwh": 87600,
        "price_dollars_per_mwh": 50.0,
        "rps_eligible_pct": 1.0,
        "vintage_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_load_forecast_payload(**overrides) -> dict:
    defaults = {
        "snapshot_label": "PLAN-2027",
        "forecast_variant": "ADOPTED_PLAN",
        "period_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_billing_extract_payload(**overrides) -> dict:
    defaults = {"billing_month": "2026-05"}
    defaults.update(overrides)
    return defaults


def create_billing_line_payload(**overrides) -> dict:
    defaults = {"service_account_id": None, "usage_kwh": 1000}
    defaults.update(overrides)
    return defaults


def create_remittance_file_payload(**overrides) -> dict:
    defaults = {
        "remittance_period": "2026-05",
        "gross_remittance_cents": 11400,
        "utility_fee_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_bad_debt_pool_payload(**overrides) -> dict:
    defaults = {"pool_period": "2026-Q2"}
    defaults.update(overrides)
    return defaults


def create_compliance_filing_payload(**overrides) -> dict:
    defaults = {"filing_type": "RPS_ANNUAL", "compliance_year": 2026}
    defaults.update(overrides)
    return defaults


def create_rec_retirement_payload(**overrides) -> dict:
    defaults = {
        "compliance_filing_id": None,
        "supply_contract_id": None,
        "retired_mwh": 100,
        "retirement_serial": "WREGIS-0001",
    }
    defaults.update(overrides)
    return defaults
