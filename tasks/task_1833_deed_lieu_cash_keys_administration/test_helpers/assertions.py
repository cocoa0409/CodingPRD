"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    AppointmentStatus,
    AppointmentType,
    CaseStatus,
    ConditionBasis,
    ConditionGrade,
    ConditionStandard,
    DismissalReason,
    DisbursementStatus,
    EvictionReason,
    EvictionStatus,
    ForeclosureReferralStatus,
    HardshipType,
    LienStatus,
    ListingStatus,
    LoanStatus,
    OccupancyType,
    ProgramType,
    RecordingStatus,
    ReportResult,
    ReportStatus,
    TitleCommitmentStatus,
    WaiverStatus,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating 'Z' and offset spellings."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Two ISO 8601 spellings of the same logical-clock instant must agree."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601, got {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_loan(data: dict):
    _assert_common(data)
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert isinstance(data["unpaid_principal_balance_cents"], int) and data["unpaid_principal_balance_cents"] > 0
    assert isinstance(data["accrued_interest_cents"], int) and data["accrued_interest_cents"] >= 0
    assert isinstance(data["escrow_advances_cents"], int) and data["escrow_advances_cents"] >= 0
    assert isinstance(data["foreclosure_fees_cents"], int) and data["foreclosure_fees_cents"] >= 0
    assert 0 < data["note_annual_rate"] <= 0.25
    assert isinstance(data["per_diem_interest_cents"], int)
    assert isinstance(data["fair_market_value_cents"], int) and data["fair_market_value_cents"] >= 0
    assert isinstance(data["delinquency_days"], int) and data["delinquency_days"] >= 0
    assert data["foreclosure_referral_status"] in [e.value for e in ForeclosureReferralStatus]
    assert data["status"] in [e.value for e in LoanStatus]
    assert isinstance(data["deficiency_balance_cents"], int) and data["deficiency_balance_cents"] >= 0
    assert isinstance(data["servicing_system_synced"], bool)


def assert_borrower(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert data["hardship_type"] in [e.value for e in HardshipType]
    assert data["self_reported_condition_grade"] in [e.value for e in ConditionGrade]


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert isinstance(data["county"], str) and data["county"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["occupancy_type"] in [e.value for e in OccupancyType]
    assert data["required_condition_standard"] in [e.value for e in ConditionStandard]


def assert_workout_case(data: dict):
    _assert_common(data)
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["borrower_id"], str) and data["borrower_id"]
    assert data["program_type"] in [e.value for e in ProgramType]
    assert data["status"] in [e.value for e in CaseStatus]
    assert isinstance(data["assigned_specialist_id"], str) and data["assigned_specialist_id"]
    assert isinstance(data["marketing_exception_granted"], bool)
    assert data.get("marketing_exception_reason") is None or isinstance(data["marketing_exception_reason"], str)
    assert isinstance(data["total_disbursed_cents"], int) and data["total_disbursed_cents"] >= 0
    assert data.get("remaining_assistance_cents") is None or isinstance(data["remaining_assistance_cents"], int)
    assert data.get("handover_date") is None or isinstance(data["handover_date"], str)
    assert isinstance(data["keys_returned"], bool)


def assert_marketing_listing(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["list_date"], str) and data["list_date"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["status"] in [e.value for e in ListingStatus]
    assert isinstance(data["creditable_days"], int) and data["creditable_days"] >= 0


def assert_listing_suspension(data: dict):
    _assert_common(data)
    assert isinstance(data["listing_id"], str) and data["listing_id"]
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert data.get("ended_at") is None or is_iso8601_timestamp(data["ended_at"])
    assert isinstance(data["reason"], str)


def assert_title_commitment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["status"] in [e.value for e in TitleCommitmentStatus]
    assert data.get("vested_owner_name") is None or isinstance(data["vested_owner_name"], str)
    assert isinstance(data["unreleased_lien_count"], int) and data["unreleased_lien_count"] >= 0


def assert_junior_lien(data: dict):
    _assert_common(data)
    assert isinstance(data["title_commitment_id"], str) and data["title_commitment_id"]
    assert isinstance(data["lienholder_name"], str) and data["lienholder_name"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["position"], int) and data["position"] >= 2
    assert data["status"] in [e.value for e in LienStatus]
    assert data.get("settlement_amount_cents") is None or isinstance(data["settlement_amount_cents"], int)
    assert data.get("released_at") is None or is_iso8601_timestamp(data["released_at"])


def assert_settlement_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["vacate_date"], str) and data["vacate_date"]
    assert isinstance(data["provisional_assistance_cents"], int) and data["provisional_assistance_cents"] >= 0
    assert data.get("final_assistance_cents") is None or isinstance(data["final_assistance_cents"], int)
    assert data["condition_basis"] in [e.value for e in ConditionBasis]
    assert data["status"] in [e.value for e in AgreementStatus]
    assert data.get("offer_expires_at") is None or is_iso8601_timestamp(data["offer_expires_at"])
    assert isinstance(data["round_number"], int) and 0 <= data["round_number"] <= 3
    assert isinstance(data["created_by_specialist_id"], str) and data["created_by_specialist_id"]


def assert_inspection_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]
    assert data["appointment_type"] in [e.value for e in AppointmentType]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in [e.value for e in AppointmentStatus]


def assert_inspection_report(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str) and data["appointment_id"]
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["status"] in [e.value for e in ReportStatus]
    assert isinstance(data["broom_clean_verified"], bool)
    assert isinstance(data["keys_returned_count"], int) and data["keys_returned_count"] >= 0
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_deduction_cents"], int) and data["total_deduction_cents"] >= 0
    assert data.get("result") is None or data["result"] in [e.value for e in ReportResult]


def assert_disbursement(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["agreement_id"], str) and data["agreement_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["purpose"] == "RELOCATION_ASSISTANCE"
    assert data["status"] in [e.value for e in DisbursementStatus]
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]
    assert data.get("approved_by_user_id") is None or isinstance(data["approved_by_user_id"], str)
    assert data.get("released_by_user_id") is None or isinstance(data["released_by_user_id"], str)
    assert data.get("released_at") is None or is_iso8601_timestamp(data["released_at"])


def assert_deficiency_waiver(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert data["status"] in [e.value for e in WaiverStatus]
    assert isinstance(data["projected_waiver_cents"], int) and data["projected_waiver_cents"] >= 0
    assert data.get("final_waiver_cents") is None or isinstance(data["final_waiver_cents"], int)
    assert data.get("pre_waiver_deficiency_cents") is None or isinstance(data["pre_waiver_deficiency_cents"], int)
    assert isinstance(data["waived_amount_cents"], int) and data["waived_amount_cents"] >= 0
    assert data.get("document_reference") is None or isinstance(data["document_reference"], str)


def assert_deed_recording(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["county"], str) and data["county"]
    assert data.get("instrument_number") is None or isinstance(data["instrument_number"], str)
    assert data["status"] in [e.value for e in RecordingStatus]
    assert data.get("recorded_at") is None or is_iso8601_timestamp(data["recorded_at"])
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)


def assert_eviction_case(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["reason"] in [e.value for e in EvictionReason]
    assert data["status"] in [e.value for e in EvictionStatus]
    assert data.get("court_reference") is None or isinstance(data["court_reference"], str)
    assert data.get("filed_at") is None or is_iso8601_timestamp(data["filed_at"])
    assert data.get("dismissal_reason") is None or data["dismissal_reason"] in [e.value for e in DismissalReason]


def assert_assistance_conservation(case: dict, applicable_assistance_cents: int):
    """INV-ASSISTANCE: total_disbursed + remaining == applicable assistance (PRD §3.5/§3.7)."""
    total = case["total_disbursed_cents"]
    remaining = case["remaining_assistance_cents"]
    assert remaining is not None, "remaining_assistance_cents must be set once an agreement exists"
    assert total + remaining == applicable_assistance_cents, (
        f"assistance conservation violated: {total} + {remaining} != {applicable_assistance_cents}"
    )


def assert_debt_conservation(loan: dict, waiver: dict):
    """INV-DEBT: deficiency_balance + waived_amount == pre_waiver_deficiency (PRD §3.8)."""
    pre = waiver["pre_waiver_deficiency_cents"]
    assert pre is not None
    assert loan["deficiency_balance_cents"] + waiver["waived_amount_cents"] == pre, (
        f"debt conservation violated: {loan['deficiency_balance_cents']} + "
        f"{waiver['waived_amount_cents']} != {pre}"
    )
