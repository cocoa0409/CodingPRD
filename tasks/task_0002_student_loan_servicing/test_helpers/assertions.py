"""Entity assertions for the Student Loan Servicing API.

Each assert_{entity} checks the field shape declared in the PRD's common-resource
contract (§2.4) and the entity's own spec sections (§3.1–§3.7). Entities marked
common_fields=true carry id + created_at + updated_at + version; ServicingEvent
and DelinquencyRecord are append-only event records carrying only id + created_at.
"""
from typing import Iterable
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


_LOAN_STATUSES = {
    "IN_SCHOOL", "GRACE", "REPAYMENT", "DEFERMENT", "FORBEARANCE",
    "DELINQUENT", "PAID_OFF", "DEFAULT", "DISCHARGED",
}
_LOAN_TYPES = {"DIRECT_SUBSIDIZED", "DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"}
_BORROWER_STATUSES = {"CURRENT", "AT_RISK", "IN_DEFAULT", "CLEARED"}
_MILITARY_STATUSES = {"NONE", "ACTIVE_DUTY", "VETERAN", "DISABLED_VETERAN"}
_PLAN_TYPES = {"STANDARD_10YR", "IBR", "PAYE", "SAVE"}
_PLAN_STATUSES = {"PENDING", "ACTIVE", "SUPERSEDED", "EXPIRED"}
_RESIDENCE_VALUES = {"CONTIGUOUS", "AK", "HI"}
_PAYMENT_STATUSES = {"PENDING", "POSTED", "REVERSED"}
_PAYMENT_SOURCES = {"ACH", "CHECK", "PAYROLL_DEDUCT", "EMPLOYER_BENEFIT", "TREASURY_OFFSET"}
_EMPLOYER_TYPES = {
    "GOVERNMENT_FEDERAL", "GOVERNMENT_STATE_LOCAL_TRIBAL", "NONPROFIT_501C3",
    "OTHER_NONPROFIT_QUALIFYING", "FOR_PROFIT", "NOT_QUALIFYING",
}
_CERTIFICATION_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
_PSLF_TRACKER_STATUSES = {"TRACKING", "ELIGIBLE_FOR_FORGIVENESS", "FORGIVEN", "DENIED"}
_DISCHARGE_TYPES = {
    "VETERAN_TOTAL_PERMANENT_DISABILITY", "PSLF_FORGIVENESS",
    "DEATH", "CLOSED_SCHOOL",
}
_DISCHARGE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED"}
_DELINQUENCY_OUTCOMES = {"OPEN", "CURED", "FORBORNE", "DEFAULTED"}


def _assert_common_mutable(data: dict, entity_label: str) -> None:
    """Check id + created_at + updated_at + version for mutable entities."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be int"
    assert data["version"] >= 1, f"{entity_label}.version must be >= 1"


def _assert_common_event(data: dict, entity_label: str) -> None:
    """Check id + created_at for append-only event entities (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )


# ─── Per-entity Assertions ────────────────────────────


def assert_borrower(data: dict) -> None:
    _assert_common_mutable(data, "Borrower")
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["email"], str)
    assert data["military_status"] in _MILITARY_STATUSES
    assert isinstance(data["aggregate_outstanding_principal_cents"], int)
    assert data["aggregate_outstanding_principal_cents"] >= 0
    assert data["borrower_status"] in _BORROWER_STATUSES


def assert_loan(data: dict) -> None:
    _assert_common_mutable(data, "Loan")
    assert is_valid_uuid(data.get("borrower_id", "")), "Loan.borrower_id must be UUID"
    assert data["loan_type"] in _LOAN_TYPES
    assert isinstance(data["original_principal_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert data["outstanding_principal_cents"] >= 0
    assert isinstance(data["accrued_interest_cents"], int)
    assert data["accrued_interest_cents"] >= 0
    assert isinstance(data["interest_rate_bps"], int)
    assert 0 <= data["interest_rate_bps"] <= 5000
    assert isinstance(data["disbursement_date"], str)
    assert data["status"] in _LOAN_STATUSES
    assert isinstance(data["subsidy_active"], bool)
    assert isinstance(data["days_delinquent"], int)
    assert data["days_delinquent"] >= 0
    assert isinstance(data["capitalized_interest_cents"], int)
    assert data["capitalized_interest_cents"] >= 0


def assert_repayment_plan(data: dict) -> None:
    _assert_common_mutable(data, "RepaymentPlan")
    assert is_valid_uuid(data.get("loan_id", ""))
    assert data["plan_type"] in _PLAN_TYPES
    assert data["state_of_residence"] in _RESIDENCE_VALUES
    assert isinstance(data["monthly_payment_cents"], int)
    assert data["monthly_payment_cents"] >= 0
    assert data["status"] in _PLAN_STATUSES
    if data["plan_type"] == "STANDARD_10YR":
        assert data.get("agi_cents") is None, (
            "STANDARD_10YR plan must have agi_cents == null"
        )
        assert data.get("family_size") is None, (
            "STANDARD_10YR plan must have family_size == null"
        )
        assert data.get("certification_expires_on") is None, (
            "STANDARD_10YR plan must have certification_expires_on == null"
        )
    else:
        assert isinstance(data.get("agi_cents"), int) and data["agi_cents"] > 0
        assert isinstance(data.get("family_size"), int) and 1 <= data["family_size"] <= 20


def assert_payment(data: dict) -> None:
    _assert_common_mutable(data, "Payment")
    assert is_valid_uuid(data.get("loan_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["posted_on"], str)
    assert data["source"] in _PAYMENT_SOURCES
    assert isinstance(data["applied_to_interest_cents"], int)
    assert data["applied_to_interest_cents"] >= 0
    assert isinstance(data["applied_to_principal_cents"], int)
    assert data["applied_to_principal_cents"] >= 0
    assert isinstance(data["applied_to_fees_cents"], int)
    assert data["applied_to_fees_cents"] >= 0
    assert data["status"] in _PAYMENT_STATUSES
    assert isinstance(data["recorded_by_user_id"], str)
    assert isinstance(data["pslf_qualifying"], bool)


def assert_servicing_event(data: dict) -> None:
    _assert_common_event(data, "ServicingEvent")
    assert is_valid_uuid(data.get("loan_id", ""))
    assert isinstance(data["event_type"], str)
    assert isinstance(data["effective_on"], str)
    assert isinstance(data["reason_code"], str)
    assert isinstance(data["created_by_user_id"], str)
    # No updated_at, no version (event records are immutable per PRD §2.4).
    assert "updated_at" not in data, (
        "ServicingEvent is append-only; must NOT expose updated_at"
    )
    assert "version" not in data, (
        "ServicingEvent is append-only; must NOT expose version"
    )


def assert_employment_certification(data: dict) -> None:
    _assert_common_mutable(data, "EmploymentCertification")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["employer_ein"], str) and len(data["employer_ein"]) == 9
    assert data["employer_type"] in _EMPLOYER_TYPES
    assert isinstance(data["period_start_on"], str)
    assert isinstance(data["period_end_on"], str)
    assert isinstance(data["weekly_hours"], (int, float))
    assert 0 <= data["weekly_hours"] <= 80
    assert data["status"] in _CERTIFICATION_STATUSES
    assert isinstance(data["pslf_qualifying_employer"], bool)


def assert_pslf_tracker(data: dict) -> None:
    _assert_common_mutable(data, "PSLFTracker")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["qualifying_payment_count"], int)
    assert data["qualifying_payment_count"] >= 0
    assert isinstance(data["required_payment_count"], int)
    assert data["status"] in _PSLF_TRACKER_STATUSES
    assert isinstance(data["last_recount_on"], str)


def assert_discharge_application(data: dict) -> None:
    _assert_common_mutable(data, "DischargeApplication")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert data["discharge_type"] in _DISCHARGE_TYPES
    assert isinstance(data["filed_on"], str)
    assert data["status"] in _DISCHARGE_STATUSES
    if data["discharge_type"] == "VETERAN_TOTAL_PERMANENT_DISABILITY":
        assert data.get("va_certification_doc_id") is not None, (
            "VA discharge application must carry va_certification_doc_id"
        )
    else:
        assert data.get("va_certification_doc_id") is None, (
            "Non-VA discharge application must NOT carry va_certification_doc_id"
        )


def assert_delinquency_record(data: dict) -> None:
    _assert_common_event(data, "DelinquencyRecord")
    assert is_valid_uuid(data.get("loan_id", ""))
    assert isinstance(data["opened_on"], str)
    assert isinstance(data["cumulative_days"], int)
    assert data["cumulative_days"] >= 0
    assert data["outcome"] in _DELINQUENCY_OUTCOMES
    # PRD §2.4: DelinquencyRecord's mutating fields (closed_on,
    # cumulative_days, outcome) are updated by the system as the
    # delinquency progresses; closed_on remains null while the record
    # is OPEN and carries a date string once closed.
    if data["outcome"] == "OPEN":
        assert data.get("closed_on") in (None, ""), (
            "Open DelinquencyRecord should have closed_on == null"
        )
    else:
        assert isinstance(data.get("closed_on"), str) and len(data["closed_on"]) > 0
    # Per PRD §2.4 DelinquencyRecord exposes neither updated_at nor version.
    assert "updated_at" not in data, (
        "DelinquencyRecord is append-only; must NOT expose updated_at"
    )
    assert "version" not in data, (
        "DelinquencyRecord is append-only; must NOT expose version"
    )
