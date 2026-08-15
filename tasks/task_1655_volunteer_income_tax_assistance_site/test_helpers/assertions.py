"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountType,
    AppointmentPurpose,
    AppointmentStatus,
    CertificationStatus,
    FilingStatus,
    FollowUpStatus,
    IdDocumentType,
    IdentityStatus,
    IntakeDocument,
    OutOfScopeFlag,
    PreferredLanguage,
    ReferralSource,
    ReferralStatus,
    RefundMethod,
    ServiceType,
    SiteReportStatus,
    SiteStatus,
    TaxReturnStatus,
    TestType,
    VolunteerStatus,
)


def _assert_common_fields(data: dict, entity: str):
    """The uniform system-managed properties every resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_site(data: dict):
    _assert_common_fields(data, "Site")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sponsor_org"], str) and data["sponsor_org"]
    assert isinstance(data["station_capacity"], int) and data["station_capacity"] >= 1
    assert is_iso8601_timestamp(data["season_start"])
    assert is_iso8601_timestamp(data["season_end"])
    assert isinstance(data["daily_open_hour"], int) and 0 <= data["daily_open_hour"] <= 23
    assert isinstance(data["daily_close_hour"], int) and 1 <= data["daily_close_hour"] <= 24
    assert data["daily_open_hour"] < data["daily_close_hour"]
    assert isinstance(data["goal_returns"], int) and data["goal_returns"] >= 1
    assert data["status"] in [s.value for s in SiteStatus]
    assert isinstance(data["accepted_count"], int) and data["accepted_count"] >= 0
    assert isinstance(data["goal_met"], bool)


def assert_volunteer(data: dict):
    _assert_common_fields(data, "Volunteer")
    assert is_valid_uuid(data.get("site_id", "")), "Volunteer.site_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["is_coordinator"], bool)
    assert data["status"] in [s.value for s in VolunteerStatus]
    assert isinstance(data["certified_test_types"], list)
    for t in data["certified_test_types"]:
        assert t in [e.value for e in TestType]
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0


def assert_certification(data: dict):
    _assert_common_fields(data, "Certification")
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["test_type"] in [e.value for e in TestType]
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert isinstance(data["tax_season"], int)
    assert isinstance(data["passed"], bool)
    assert data["status"] in [s.value for s in CertificationStatus]
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1


def assert_taxpayer(data: dict):
    _assert_common_fields(data, "Taxpayer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_token"], str) and data["ssn_token"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert data.get("email") is None or isinstance(data["email"], str)
    assert data["preferred_language"] in [e.value for e in PreferredLanguage]
    assert data["identity_status"] in [s.value for s in IdentityStatus]
    assert data.get("id_document_type") is None or data["id_document_type"] in [
        e.value for e in IdDocumentType
    ]


def assert_appointment(data: dict):
    _assert_common_fields(data, "Appointment")
    for fk in ("site_id", "taxpayer_id", "volunteer_id"):
        assert is_valid_uuid(data.get(fk, "")), f"Appointment.{fk} must be a UUID"
    assert data["purpose"] in [e.value for e in AppointmentPurpose]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in [s.value for s in AppointmentStatus]


def assert_tax_return(data: dict):
    _assert_common_fields(data, "TaxReturn")
    for fk in ("appointment_id", "taxpayer_id", "site_id", "preparer_id"):
        assert is_valid_uuid(data.get(fk, "")), f"TaxReturn.{fk} must be a UUID"
    assert data.get("reviewer_id") is None or is_valid_uuid(data["reviewer_id"])
    assert isinstance(data["tax_year"], int)
    assert data["filing_status"] in [e.value for e in FilingStatus]
    assert isinstance(data["has_advanced_scope_items"], bool)
    assert isinstance(data["out_of_scope_flags"], list)
    for f in data["out_of_scope_flags"]:
        assert f in [e.value for e in OutOfScopeFlag]
    assert data["status"] in [s.value for s in TaxReturnStatus]
    assert isinstance(data["documents_received"], list)
    for d in data["documents_received"]:
        assert d in [e.value for e in IntakeDocument]
    assert isinstance(data["interview_confirmed"], bool)
    for money in (
        "wages_cents",
        "other_income_cents",
        "earned_income_cents",
        "withholding_reported_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0
    assert data.get("withholding_verified_cents") is None or (
        isinstance(data["withholding_verified_cents"], int)
        and data["withholding_verified_cents"] >= 0
    )
    assert isinstance(data["qualifying_children"], int) and 0 <= data["qualifying_children"] <= 10
    assert data["refund_method"] in [e.value for e in RefundMethod]
    assert isinstance(data["documents_complete"], bool)
    assert isinstance(data["out_of_scope"], bool)
    assert isinstance(data["out_of_scope_reasons"], list)
    assert isinstance(data["estimated_refund_cents"], int)
    assert data.get("final_refund_cents") is None or isinstance(data["final_refund_cents"], int)
    assert isinstance(data["savings_match_cents"], int) and data["savings_match_cents"] >= 0
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0
    assert data.get("first_ack_outcome") is None or data["first_ack_outcome"] in [
        "ACCEPTED",
        "REJECTED",
    ]
    assert isinstance(data["qr_failure_count"], int) and data["qr_failure_count"] >= 0
    assert isinstance(data["reached_preparation"], bool)


def assert_refund_allocation(data: dict):
    _assert_common_fields(data, "RefundAllocation")
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert data["account_type"] in [e.value for e in AccountType]
    assert isinstance(data["routing_number"], str) and len(data["routing_number"]) == 9
    assert data["routing_number"].isdigit()
    assert isinstance(data["account_number_mask"], str) and data["account_number_mask"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_efile_rejection(data: dict):
    _assert_common_fields(data, "EfileRejection")
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert isinstance(data["rejection_code"], str) and data["rejection_code"]
    assert isinstance(data["rejection_text"], str) and data["rejection_text"]
    assert isinstance(data["submission_number"], int) and data["submission_number"] >= 1
    assert data["follow_up_status"] in [s.value for s in FollowUpStatus]
    assert is_iso8601_timestamp(data["follow_up_due_at"])
    assert isinstance(data["follow_up_overdue"], bool)


def assert_site_report(data: dict):
    _assert_common_fields(data, "SiteReport")
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in [s.value for s in SiteReportStatus]
    assert is_iso8601_timestamp(data["generated_at"])
    for count in (
        "returns_prepared_count",
        "returns_transmitted_count",
        "returns_accepted_count",
        "returns_rejected_open_count",
        "returns_referred_count",
        "returns_withdrawn_count",
        "qr_rework_total",
        "first_pass_accepted_count",
        "financial_referrals_accepted_count",
        "savings_match_total_cents",
    ):
        assert isinstance(data[count], int) and data[count] >= 0, (
            f"SiteReport.{count} must be a non-negative integer"
        )
    for rate in ("first_pass_acceptance_rate_bp", "final_resolution_rate_bp"):
        assert data.get(rate) is None or (isinstance(data[rate], int) and data[rate] >= 0)


def assert_financial_service_referral(data: dict):
    _assert_common_fields(data, "FinancialServiceReferral")
    assert is_valid_uuid(data.get("tax_return_id", ""))
    assert data["service_type"] in [e.value for e in ServiceType]
    assert data["status"] in [s.value for s in ReferralStatus]
    assert data.get("offered_by") is None or isinstance(data["offered_by"], str)
    assert data["source"] in [e.value for e in ReferralSource]


def assert_case_load_invariant(volunteer: dict):
    """active_case_count is a non-negative cardinality (PRD §3.2)."""
    assert volunteer["active_case_count"] >= 0


def assert_refund_conservation(allocations: list, expected_total_cents: int):
    """sum(amount_cents) over a return's allocations equals the expected total."""
    total = sum(a["amount_cents"] for a in allocations)
    assert total == expected_total_cents, (
        f"Allocation total {total} drifted from expected {expected_total_cents}"
    )
