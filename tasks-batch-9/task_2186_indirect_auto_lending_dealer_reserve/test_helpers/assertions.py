"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AgreementStatus, ApplicationStatus, BuybackStatus, DealerStatus,
    DocumentStatus, EntryType, FundingStatus, Grade, RateSheetStatus,
    ReserveStatus, ReviewFinding, ReviewStatus, ScorecardStatus,
)

MUTABLE_AUDIT_FIELDS = ("updated_at", "version")


def _assert_identity(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert "_" not in str(data.get("id", "")), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )


def _assert_versioned(data: dict, label: str):
    _assert_identity(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_history_row_has_no_mutable_audit_fields(data: dict, label: str):
    """Historical rows carry only id and created_at."""
    for field in MUTABLE_AUDIT_FIELDS:
        assert field not in data, (
            f"{label} is a historical record and must not expose '{field}', got {data.get(field)!r}"
        )


def assert_dealer(data: dict):
    _assert_versioned(data, "Dealer")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code must be two uppercase letters"
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["funding_line_cents"], int) and data["funding_line_cents"] >= 0
    assert data["status"] in [s.value for s in DealerStatus]
    assert isinstance(data["compliance_hold"], bool)
    assert isinstance(data["reserve_balance_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["funded_contract_count"], int)
    assert isinstance(data["total_funded_ever_count"], int)
    assert isinstance(data["early_payoff_count"], int)
    assert isinstance(data["default_count"], int)
    assert isinstance(data["repurchase_count"], int)
    assert isinstance(data["chargeback_count"], int)
    assert isinstance(data["early_payoff_rate_bps"], int)
    assert data["latest_scorecard_grade"] is None or data["latest_scorecard_grade"] in [
        g.value for g in Grade
    ]
    assert isinstance(data["scorecard_stale"], bool)


def assert_agreement(data: dict):
    _assert_versioned(data, "DealerAgreement")
    assert is_valid_uuid(data["dealer_id"])
    assert data["participation_method"] in ("RATE_PARTICIPATION", "FLAT_FEE")
    assert isinstance(data["max_participation_bps"], int)
    assert 0 <= data["max_participation_bps"] <= 250
    assert isinstance(data["flat_fee_cap_cents"], int) and data["flat_fee_cap_cents"] >= 0
    assert isinstance(data["chargeback_window_days"], int)
    assert data["chargeback_window_days"] % 30 == 0
    assert 60 <= data["chargeback_window_days"] <= 720
    assert data["status"] in [s.value for s in AgreementStatus]
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])


def assert_rate_sheet(data: dict):
    _assert_versioned(data, "RateSheet")
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["status"] in [s.value for s in RateSheetStatus]
    assert isinstance(data["tier_count"], int) and data["tier_count"] >= 0


def assert_rate_sheet_tier(data: dict):
    _assert_identity(data, "RateSheetTier")
    assert_history_row_has_no_mutable_audit_fields(data, "RateSheetTier")
    assert data["tier_code"] in ("T1", "T2", "T3")
    assert 300 <= data["min_credit_score"] <= 900
    assert 300 <= data["max_credit_score"] <= 900
    assert data["max_credit_score"] >= data["min_credit_score"]
    assert 50 <= data["max_ltv_pct"] <= 150
    assert 12 <= data["max_term_months"] <= 96
    assert 50 <= data["advance_rate_pct"] <= 150
    assert 0 <= data["buy_rate_apr_bps"] <= 3000
    assert data["acquisition_fee_cents"] >= 0


def assert_application(data: dict):
    _assert_versioned(data, "CreditApplication")
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["applicant_reference"], str)
    assert 1 <= len(data["applicant_reference"]) <= 64
    assert data["monitoring_cohort"] in ("CONTROL", "MONITORED")
    assert 300 <= data["credit_score"] <= 900
    assert data["monthly_income_cents"] > 0
    assert data["monthly_debt_cents"] >= 0
    assert data["amount_financed_cents"] > 0
    assert data["collateral_value_cents"] > 0
    assert 12 <= data["term_months"] <= 96
    assert 1990 <= data["vehicle_model_year"] <= 2030
    assert 0 <= data["requested_apr_bps"] <= 3600
    assert isinstance(data["ltv_pct"], (int, float))
    assert isinstance(data["dti_pct"], (int, float))
    assert data["demotion_count"] in (0, 1, 2)
    assert data["status"] in [s.value for s in ApplicationStatus]
    assert isinstance(data["resubmission_count"], int)
    assert isinstance(data["stipulation_count"], int)


def assert_contract(data: dict):
    _assert_versioned(data, "RetailContract")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert data["funding_status"] in [s.value for s in FundingStatus]
    assert data["reserve_status"] in [s.value for s in ReserveStatus]
    assert isinstance(data["required_doc_types"], list)
    assert data["markup_bps"] == data["contract_apr_bps"] - data["buy_rate_apr_bps"]
    assert isinstance(data["verified_doc_count"], int)
    assert isinstance(data["doc_defect_count"], int)
    assert isinstance(data["reserve_accrued_cents"], int)
    assert isinstance(data["incentive_accrued_cents"], int)
    assert isinstance(data["dealer_proceeds_cents"], int)
    assert isinstance(data["unpaid_principal_cents"], int)


def assert_document(data: dict):
    _assert_versioned(data, "ContractDocument")
    assert is_valid_uuid(data["contract_id"])
    assert data["doc_type"] in (
        "RETAIL_INSTALLMENT_CONTRACT", "TITLE_APPLICATION",
        "INSURANCE_BINDER", "INCOME_VERIFICATION",
    )
    assert isinstance(data["document_reference"], str)
    assert 1 <= len(data["document_reference"]) <= 64
    assert data["status"] in [s.value for s in DocumentStatus]


def assert_reserve_entry(data: dict):
    _assert_identity(data, "ReserveEntry")
    assert_history_row_has_no_mutable_audit_fields(data, "ReserveEntry")
    assert is_valid_uuid(data["dealer_id"])
    assert data["entry_type"] in [e.value for e in EntryType]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reason"], str) and 1 <= len(data["reason"]) <= 120
    assert isinstance(data["balance_after_cents"], int)


def assert_chargeback_event(data: dict):
    _assert_identity(data, "ChargebackEvent")
    assert_history_row_has_no_mutable_audit_fields(data, "ChargebackEvent")
    assert is_valid_uuid(data["contract_id"])
    assert data["event_type"] in ("EARLY_PAYOFF", "DEFAULT")
    assert isinstance(data["months_seasoned"], int)
    assert isinstance(data["window_months"], int)
    assert isinstance(data["within_window"], bool)
    assert isinstance(data["participation_chargeback_cents"], int)
    assert isinstance(data["incentive_chargeback_cents"], int)
    assert isinstance(data["chargeback_total_cents"], int)
    assert isinstance(data["earned_to_date_reserve_cents"], int)


def assert_scorecard(data: dict):
    _assert_versioned(data, "DealerScorecard")
    assert is_valid_uuid(data["dealer_id"])
    assert data["basis"] in ("TRAILING_WINDOW", "INCEPTION_TO_DATE")
    assert data["status"] in [s.value for s in ScorecardStatus]
    assert data["grade"] in [g.value for g in Grade]
    assert isinstance(data["population_count"], int)
    for field in ("default_rate_bps", "early_payoff_rate_bps",
                  "doc_defect_rate_bps", "avg_markup_bps"):
        assert isinstance(data[field], int), f"{field} must be whole basis points"
    if data["composite_score"] is not None:
        assert 0 <= data["composite_score"] <= 1000


def assert_review(data: dict):
    _assert_versioned(data, "FairLendingReview")
    assert is_valid_uuid(data["dealer_id"])
    assert data["status"] in [s.value for s in ReviewStatus]
    assert data["finding"] in [f.value for f in ReviewFinding]
    assert isinstance(data["population_count"], int)
    assert isinstance(data["benchmark_markup_bps"], int)
    assert isinstance(data["control_avg_markup_bps"], int)
    assert isinstance(data["monitored_avg_markup_bps"], int)
    assert isinstance(data["disparity_bps"], int)
    assert isinstance(data["remediation_pool_cents"], int)
    assert data["disparity_bps"] == (
        data["monitored_avg_markup_bps"] - data["control_avg_markup_bps"]
    )


def assert_buyback_demand(data: dict):
    _assert_versioned(data, "BuybackDemand")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert data["status"] in [s.value for s in BuybackStatus]
    assert data["reason"] in (
        "DOC_DEFECT", "EARLY_DEFAULT", "FRAUD", "DEALER_TERMINATION",
    )
    assert data["buyback_amount_cents"] == (
        data["unpaid_principal_cents"] + data["reserve_offset_cents"] + data["admin_fee_cents"]
    ), "buyback_amount_cents must be unpaid principal plus reserve offset plus admin fee"


def assert_ledger_balance_matches_entries(dealer: dict, entries: list):
    """The dealership's reserve balance is the signed sum of its ledger."""
    total = sum(entry["amount_cents"] for entry in entries)
    assert dealer["reserve_balance_cents"] == total, (
        f"reserve_balance_cents {dealer['reserve_balance_cents']} must equal "
        f"the signed sum of ledger amount_cents {total}"
    )
