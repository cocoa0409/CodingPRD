"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_bank(data: dict):
    """Validate Bank response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["charter_id"], str) and len(data["charter_id"]) > 0
    assert data["rwa_methodology"] in ("STANDARDIZED", "ADVANCED")
    assert data["pca_bucket"] in (
        "WELL_CAPITALIZED",
        "ADEQUATELY_CAPITALIZED",
        "UNDERCAPITALIZED",
        "SIGNIFICANTLY_UNDERCAPITALIZED",
        "CRITICALLY_UNDERCAPITALIZED",
    )
    assert isinstance(data["mdba_cents"], int)
    assert isinstance(data["pending_distribution_cents"], int)
    assert data["supervisory_status"] in ("NORMAL", "UNDER_LETTER", "UNDER_MOU")


def assert_reporting_period(data: dict):
    """Validate ReportingPeriod response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["period_end_date"], str)
    assert isinstance(data["period_year"], int)
    assert data["period_quarter"] in ("Q1", "Q2", "Q3", "Q4")
    assert is_iso8601_timestamp(data.get("filing_due_at", "")), "filing_due_at must be ISO 8601"
    assert isinstance(data["late_filing"], bool)
    assert data["status"] in (
        "OPEN", "FILING_DUE", "SUBMITTED", "ACCEPTED",
        "AMENDMENT_OPEN", "RE_SUBMITTED", "RE_ACCEPTED", "CLOSED",
    )


def assert_capital_instrument(data: dict):
    """Validate CapitalInstrument response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert data["instrument_class"] in ("CET1", "AT1", "T2")
    assert data["instrument_subtype"] in (
        "COMMON_STOCK", "PREFERRED", "TRUST_PREFERRED", "SUBORDINATED_DEBT", "OTHER",
    )
    assert isinstance(data["outstanding_amount_cents"], int)
    assert isinstance(data["issuance_date"], str)
    assert isinstance(data["contractual_rate_bps"], int)
    assert data["status"] in ("OUTSTANDING", "CALLED", "MATURED", "REDEEMED")


def assert_risk_exposure(data: dict):
    """Validate RiskExposure response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["reporting_period_id"], str)
    assert data["exposure_class"] in (
        "SOVEREIGN", "CORPORATE", "RETAIL_MORTGAGE", "RETAIL_OTHER", "CRE",
        "HVCRE", "EQUITY", "SECURITIZATION", "OPERATIONAL_RISK", "MARKET_RISK",
    )
    assert isinstance(data["exposure_at_default_cents"], int)
    assert isinstance(data["risk_weight_bps"], int)
    assert data["obligor_grade"] in ("INVESTMENT_GRADE", "NON_INVESTMENT_GRADE", "DEFAULT")
    assert isinstance(data["rwa_cents_standardized"], int)
    assert isinstance(data["rwa_cents_advanced"], int)


def assert_capital_plan(data: dict):
    """Validate CapitalPlan response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["baseline_period_id"], str)
    assert isinstance(data["stress_scenario_id"], str)
    assert data["status"] in (
        "DRAFT", "BOARD_REVIEW", "SUBMITTED", "SUPERVISORY_REVIEW",
        "APPROVED", "OBJECTED", "EFFECTIVE", "SUPERSEDED",
    )


def assert_stress_scenario(data: dict):
    """Validate StressScenario response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["scenario_code"], str)
    assert isinstance(data["gdp_shock_bps"], int)
    assert isinstance(data["unemployment_peak_bps"], int)
    assert isinstance(data["hpi_shock_bps"], int)
    assert isinstance(data["cre_price_shock_bps"], int)
    assert isinstance(data["market_shock_bps"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_call_report(data: dict):
    """Validate CallReport response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["reporting_period_id"], str)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["amendment_sequence"], int)
    assert isinstance(data["edit_failures_open_count"], int)
    assert isinstance(data["edit_failures_total_count"], int)
    assert data["status"] in (
        "DRAFT", "PREPARED", "EDITS_OUTSTANDING", "VALIDATED",
        "SUBMITTED", "ACCEPTED", "AMENDED_SUPERSEDED",
    )


def assert_edit_exception(data: dict):
    """Validate EditException response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["call_report_id"], str)
    assert isinstance(data["edit_code"], str)
    assert data["severity"] in ("FATAL", "QUALITY", "INFORMATIONAL")
    assert data["status"] in ("OPEN", "RESOLVED", "EXPLAINED")


def assert_distribution_request(data: dict):
    """Validate CapitalDistributionRequest response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["capital_plan_id"], str)
    assert isinstance(data["reporting_period_id"], str)
    assert data["distribution_kind"] in ("DIVIDEND", "BUYBACK")
    assert isinstance(data["distribution_amount_cents"], int)
    assert isinstance(data["proposed_payment_date"], str)
    assert data["status"] in (
        "PROPOSED", "APPROVED_NOT_EXECUTED", "EXECUTED",
        "REJECTED", "WITHDRAWN", "EXPIRED",
    )


def assert_sub_debt_issuance(data: dict):
    """Validate SubordinatedDebtIssuance response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["proposed_amount_cents"], int)
    assert isinstance(data["proposed_rate_bps"], int)
    assert isinstance(data["maturity_years"], int)
    assert isinstance(data["target_settlement_date"], str)
    assert data["status"] in ("PROPOSED", "APPROVED", "PRICED", "SETTLED", "WITHDRAWN")


def assert_pca_threshold_event(data: dict):
    """Validate PCAThresholdEvent response structure against PRD contract.

    Immutable audit record: carries id and created_at only of the common
    set — updated_at and version are absent (PRD §2.4).
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["call_report_id"], str)
    assert data["metric"] in ("CET1", "TIER1", "TOTAL", "LEVERAGE")
    assert isinstance(data["ratio_bps_observed"], int)
    assert isinstance(data["bucket_before"], str)
    assert isinstance(data["bucket_after"], str)
    assert isinstance(data["breached"], bool)


def assert_icaap_document(data: dict):
    """Validate ICAAPDocument response structure against PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["document_year"], int)
    assert isinstance(data["governing_capital_plan_id"], str)
    assert isinstance(data["sections"], list)
    assert data["status"] in ("DRAFT", "REVIEW", "ATTESTED", "FILED", "SUPERSEDED")


def assert_bank_invariants(data: dict):
    """Bank-level invariants that must hold after any operation (PRD §3.6)."""
    assert data["mdba_cents"] >= 0, "mdba_cents is floored at zero"
    assert data["pending_distribution_cents"] >= 0, "pending distribution pool cannot be negative"
