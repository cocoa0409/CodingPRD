"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "RWA_CENTS": 100_000_000_000,          # 100e9 RWA via one 100%-weighted CORPORATE line
    "CET1_CENTS": 10_000_000_000,          # 10e9 CET1 -> 1000 bps ratio at default RWA
    "PERIOD_END_DATE": "2026-06-30",
    "PERIOD_YEAR": 2026,
    "PERIOD_QUARTER": "Q2",
    "ISSUANCE_DATE": "2020-01-15",
    "PLAN_YEAR": 2027,
    "PAYMENT_DATE": "2027-03-15",
    "DOCUMENT_YEAR": 2027,
}

MILD_SCENARIO = {
    "gdp_shock_bps": -100,
    "unemployment_peak_bps": 600,
    "hpi_shock_bps": -500,
    "cre_price_shock_bps": -500,
    "market_shock_bps": -1000,
}

SEVERE_SCENARIO = {
    "gdp_shock_bps": -300,
    "unemployment_peak_bps": 1000,
    "hpi_shock_bps": -2000,
    "cre_price_shock_bps": -2500,
    "market_shock_bps": -3000,
}


def create_bank_payload(**overrides) -> dict:
    defaults = {"legal_name": "Test Bank", "charter_id": "CH-TEST-000"}
    defaults.update(overrides)
    return defaults


def create_reporting_period_payload(**overrides) -> dict:
    defaults = {
        "period_end_date": DEFAULTS["PERIOD_END_DATE"],
        "period_year": DEFAULTS["PERIOD_YEAR"],
        "period_quarter": DEFAULTS["PERIOD_QUARTER"],
    }
    defaults.update(overrides)
    return defaults


def create_capital_instrument_payload(**overrides) -> dict:
    defaults = {
        "instrument_class": "CET1",
        "instrument_subtype": "COMMON_STOCK",
        "outstanding_amount_cents": DEFAULTS["CET1_CENTS"],
        "issuance_date": DEFAULTS["ISSUANCE_DATE"],
        "contractual_rate_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_risk_exposure_payload(reporting_period_id: str, **overrides) -> dict:
    defaults = {
        "reporting_period_id": reporting_period_id,
        "exposure_class": "CORPORATE",
        "exposure_at_default_cents": DEFAULTS["RWA_CENTS"],
        "risk_weight_bps": 10000,
        "obligor_grade": "INVESTMENT_GRADE",
        "collateral_haircut_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_stress_scenario_payload(**overrides) -> dict:
    defaults = {"scenario_code": "BASE-SCEN", **MILD_SCENARIO}
    defaults.update(overrides)
    return defaults


def create_capital_plan_payload(baseline_period_id: str, stress_scenario_id: str, **overrides) -> dict:
    defaults = {
        "plan_year": DEFAULTS["PLAN_YEAR"],
        "baseline_period_id": baseline_period_id,
        "stress_scenario_id": stress_scenario_id,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_request_payload(
    capital_plan_id: str, reporting_period_id: str, **overrides
) -> dict:
    defaults = {
        "capital_plan_id": capital_plan_id,
        "reporting_period_id": reporting_period_id,
        "distribution_kind": "DIVIDEND",
        "distribution_amount_cents": 50_000_000,
        "proposed_payment_date": DEFAULTS["PAYMENT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_sub_debt_issuance_payload(**overrides) -> dict:
    defaults = {
        "proposed_amount_cents": 500_000_000,
        "proposed_rate_bps": 500,
        "maturity_years": 10,
        "target_settlement_date": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_icaap_document_payload(governing_capital_plan_id: str, **overrides) -> dict:
    defaults = {
        "document_year": DEFAULTS["DOCUMENT_YEAR"],
        "governing_capital_plan_id": governing_capital_plan_id,
        "sections": [
            {"section_code": code, "content": f"{code} section content"}
            for code in (
                "GOVERNANCE",
                "RISK_APPETITE",
                "CAPITAL_ADEQUACY",
                "STRESS_TESTING",
                "DISTRIBUTION_POLICY",
            )
        ],
    }
    defaults.update(overrides)
    return defaults
