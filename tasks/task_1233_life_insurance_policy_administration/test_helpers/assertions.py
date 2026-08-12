"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationStatus,
    BillingCycleStatus,
    ConversionStatus,
    DividendOption,
    DividendStatus,
    ElectionType,
    FormStatus,
    Gender,
    LedgerEntryType,
    LoanStatus,
    PremiumMode,
    PremiumPaymentStatus,
    ProductType,
    ReinstatementStatus,
    RiderStatus,
    RiderType,
    UnderwritingClass,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID without type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_append_only(data: dict, entity: str):
    # Append-only families carry only id + created_at (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at ISO 8601"
    assert "updated_at" not in data, f"{entity} must not expose updated_at (append-only)"
    assert "version" not in data, f"{entity} must not expose version (append-only)"


def assert_insured_person(data: dict):
    _assert_common(data, "InsuredPerson")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["tobacco_user"], bool)
    assert data["gender"] in [g.value for g in Gender]


def assert_product_template(data: dict):
    _assert_common(data, "ProductTemplate")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["product_type"] in [p.value for p in ProductType]
    assert isinstance(data["participating"], bool)
    assert isinstance(data["allows_policy_loans"], bool)
    assert data["min_face_amount_cents"] <= data["max_face_amount_cents"]
    assert isinstance(data["coi_rate_table"], list)
    assert isinstance(data["surrender_charge_schedule"], list)


def assert_application(data: dict):
    _assert_common(data, "PolicyApplication")
    assert data["status"] in [s.value for s in ApplicationStatus]
    assert isinstance(data["requested_face_amount_cents"], int)
    assert data["premium_mode"] in [m.value for m in PremiumMode]
    if data.get("underwriting_class") is not None:
        assert data["underwriting_class"] in [c.value for c in UnderwritingClass]


def assert_policy(data: dict):
    _assert_common(data, "Policy")
    assert data["premium_payment_status"] in [s.value for s in PremiumPaymentStatus]
    assert data["form_status"] in [s.value for s in FormStatus]
    assert isinstance(data["face_amount_cents"], int)
    assert isinstance(data["modal_premium_cents"], int)
    assert isinstance(data["cash_value_cents"], int)
    assert isinstance(data["outstanding_loan_principal_cents"], int)
    assert isinstance(data["accrued_loan_interest_cents"], int)
    assert isinstance(data["dividend_accumulation_cents"], int)
    assert data["premium_mode"] in [m.value for m in PremiumMode]
    if data.get("dividend_option") is not None:
        assert data["dividend_option"] in [o.value for o in DividendOption]


def assert_billing_cycle(data: dict):
    _assert_common(data, "PremiumBillingCycle")
    assert data["status"] in [s.value for s in BillingCycleStatus]
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["due_amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)


def assert_policy_loan(data: dict):
    _assert_common(data, "PolicyLoan")
    assert data["status"] in [s.value for s in LoanStatus]
    assert data["annual_interest_rate_bps"] == 500, "carrier-fixed at 500 bps (PRD §3.6)"
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)


def assert_loan_interest_accrual(data: dict):
    _assert_append_only(data, "LoanInterestAccrual")
    assert isinstance(data["principal_base_cents"], int)
    assert isinstance(data["days_accrued"], int)
    assert isinstance(data["interest_accrued_cents"], int)


def assert_dividend_declaration(data: dict):
    _assert_common(data, "DividendDeclaration")
    assert data["status"] in [s.value for s in DividendStatus]
    assert isinstance(data["declared_amount_cents"], int)
    assert isinstance(data["applied_amount_cents"], int)


def assert_nonforfeiture_election(data: dict):
    _assert_common(data, "NonforfeitureElection")
    assert data["election_type"] in [e.value for e in ElectionType]
    for f in ("cash_value_at_election_cents", "outstanding_loan_offset_cents",
              "surrender_charge_cents", "net_available_cents",
              "resulting_face_amount_cents", "resulting_term_months", "payout_cents"):
        assert isinstance(data[f], int), f"NonforfeitureElection.{f} must be int"


def assert_reinstatement_request(data: dict):
    _assert_common(data, "ReinstatementRequest")
    assert data["status"] in [s.value for s in ReinstatementStatus]
    assert isinstance(data["back_premium_due_cents"], int)
    assert isinstance(data["back_premium_paid_cents"], int)
    assert isinstance(data["evidence_of_insurability"], bool)


def assert_rider(data: dict):
    _assert_common(data, "Rider")
    assert data["rider_type"] in [t.value for t in RiderType]
    assert data["status"] in [s.value for s in RiderStatus]
    assert isinstance(data["rider_face_amount_cents"], int)


def assert_conversion_request(data: dict):
    _assert_common(data, "ConversionRequest")
    assert data["status"] in [s.value for s in ConversionStatus]
    assert isinstance(data["requested_face_amount_cents"], int)


def assert_cash_value_ledger_entry(data: dict):
    _assert_append_only(data, "CashValueLedgerEntry")
    assert data["entry_type"] in [t.value for t in LedgerEntryType]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["resulting_cash_value_cents"], int)


def assert_policy_loan_invariants(policy: dict):
    """Policy-level loan/cash invariants that must hold after any operation."""
    assert policy["outstanding_loan_principal_cents"] >= 0
    assert policy["accrued_loan_interest_cents"] >= 0
