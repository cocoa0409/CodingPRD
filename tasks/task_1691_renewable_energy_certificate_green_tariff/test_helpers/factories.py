"""Payload factories — one per creatable entity, input fields only.

Defaults are deliberately boring and valid; every factory accepts overrides.
Fields the server computes or defaults (status, computed counters, server
timestamps) are never emitted here.
"""
import uuid


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def create_generator_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _uniq("Sierra Solar"),
        "facility_code": _uniq("SS"),
        "technology": "SOLAR",
        "nameplate_capacity_kw": 5000,
        "region_code": "CAISO",
        "commissioning_date": "2020-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-08-01T00:00:00Z",
        "metered_kwh": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_type": "BROKER",
        "owner_name": _uniq("Broker"),
    }
    defaults.update(overrides)
    return defaults


def create_trade_payload(**overrides) -> dict:
    defaults = {
        "unit_price_cents_per_mwh": 300,
        "settlement_mode": "GROSS",
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("SunTariff"),
        "market_class": "VOLUNTARY",
        "eligible_region_codes": ["CAISO"],
        "eligible_technologies": ["SOLAR"],
        "capacity_cap_kw": 1000,
        "rate_tiers": [{"up_to_kwh": 500, "rate_cents_per_kwh": 5}],
        "annual_claim_cap_mwh": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "customer_name": _uniq("Customer"),
        "utility_account_no": _uniq("U"),
        "allocation_kw": 100,
        "estimated_usage_kwh": 900,
    }
    defaults.update(overrides)
    return defaults


def create_bill_payload(**overrides) -> dict:
    defaults = {
        "period_month": "2026-07",
        "usage_kwh": 1000,
        "charges_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_retirement_payload(**overrides) -> dict:
    return dict(overrides)


def create_obligation_payload(**overrides) -> dict:
    defaults = {
        "lse_name": _uniq("LSE"),
        "year": 2026,
        "region_code": "CAISO",
        "required_mwh": 500,
        "penalty_rate_cents_per_mwh": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_report_payload(**overrides) -> dict:
    defaults = {
        "scope": "VOLUNTARY_PROGRAM",
        "report_year": 2026,
    }
    defaults.update(overrides)
    return defaults
