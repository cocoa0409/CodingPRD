"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

_deal_seq = {"n": 0}


def _next_deal_code() -> str:
    _deal_seq["n"] += 1
    return f"D-{_deal_seq['n']:04d}"


def create_deal_payload(**overrides) -> dict:
    defaults = {
        "deal_code": _next_deal_code(),
        "deal_name": "Test Deal",
        "strategy": "CORE",
        "target_purchase_price_cents": TEST_DEFAULTS["DEAL_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "address_line": "1 Main St",
        "market": "Austin, TX",
        "property_type": "MULTIFAMILY",
        "units": 10,
        "rentable_sqft": 20_000,
        "year_built": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_rent_roll_payload(**overrides) -> dict:
    defaults = {
        "period_month": "2026-06",
        "occupied_units": 9,
        "total_units": 10,
        "gross_potential_rent_cents": 1_000_000,
        "collected_rent_cents": 900_000,
        "concessions_cents": 0,
        "source_doc_ref": "rr",
    }
    defaults.update(overrides)
    return defaults


def create_operating_expense_payload(**overrides) -> dict:
    defaults = {
        "period_year": 2025,
        "category": "TAXES",
        "amount_cents": 1_000_000,
        "is_recoverable": False,
    }
    defaults.update(overrides)
    return defaults


def create_assumption_payload(**overrides) -> dict:
    defaults = dict(TEST_DEFAULTS["ASSUMPTION"])
    defaults.update(overrides)
    return defaults


def create_scenario_payload(assumption_id, expected_deal_version, **overrides) -> dict:
    defaults = {
        "scenario_kind": "BASE",
        "assumption_id": assumption_id,
        "occupancy_stress_pct": 90,
        "expected_deal_version": expected_deal_version,
    }
    defaults.update(overrides)
    return defaults


def create_ic_memo_payload(scenario_id, expected_deal_version, **overrides) -> dict:
    defaults = {
        "scenario_id": scenario_id,
        "recommendation": "PURSUE",
        "thesis": "t",
        "risks": "r",
        "expected_deal_version": expected_deal_version,
    }
    defaults.update(overrides)
    return defaults


def create_debt_sizing_payload(**overrides) -> dict:
    defaults = {
        "interest_rate_bps": 550,
        "amortization_years": 30,
        "io_months": 0,
        "min_dscr_pct": 125,
        "max_ltv_pct": 65,
    }
    defaults.update(overrides)
    return defaults


def create_waterfall_payload(**overrides) -> dict:
    defaults = {
        "pref_return_bps": 800,
        "promote_tier1_bps": 2000,
        "tier1_hurdle_bps": 1200,
        "promote_tier2_bps": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    defaults = {"vote": "YES"}
    defaults.update(overrides)
    return defaults
