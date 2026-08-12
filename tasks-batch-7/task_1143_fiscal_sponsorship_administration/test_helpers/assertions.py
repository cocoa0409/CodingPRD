"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    ApplicationStatus,
    DisbursementStatus,
    DonationStatus,
    EngagementStatus,
    ExitPlanStatus,
    FeeAssessmentStatus,
    FundStatus,
    IncidentStatus,
    LedgerEntryType,
    OversightPosture,
    ProjectStatus,
    ReceiptStatus,
    ReviewStatus,
    TrancheStatus,
)


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be an integer starting at 1"
    )


def assert_application(data: dict):
    _assert_common_fields(data, "ProjectApplication")
    assert data["status"] in [s.value for s in ApplicationStatus]
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert isinstance(data["mission_statement"], str)
    assert isinstance(data["budget_estimate_cents"], int)
    assert isinstance(data["submit_count"], int) and data["submit_count"] >= 0


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert data["status"] in [s.value for s in ProjectStatus]
    assert data["oversight_posture"] in [p.value for p in OversightPosture]
    assert isinstance(data["risk_score"], int)


def assert_agreement(data: dict):
    _assert_common_fields(data, "SponsorshipAgreement")
    assert data["status"] in [s.value for s in AgreementStatus]
    assert data["model"] in ["COMPREHENSIVE", "PRE_APPROVED_GRANT"]
    assert data["spending_basis"] in ["SETTLED", "FORWARD_LOOKING"]


def assert_fund_account(data: dict):
    _assert_common_fields(data, "FundAccount")
    assert data["status"] in [s.value for s in FundStatus]
    for field in (
        "total_received_cents", "total_refunded_cents", "total_fees_charged_cents",
        "total_fees_reversed_cents", "total_disbursed_cents", "total_adjustments_cents",
        "total_transferred_out_cents", "committed_cents", "reserved_cents",
        "available_cents", "forward_available_cents",
    ):
        assert isinstance(data[field], int), f"FundAccount.{field} must be integer cents"


def assert_ledger_entry(data: dict):
    """PRD §2.5: a FundLedgerEntry carries only id and created_at (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "FundLedgerEntry: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "FundLedgerEntry: created_at must be ISO 8601"
    assert "version" not in data, "FundLedgerEntry must not carry version"
    assert "updated_at" not in data, "FundLedgerEntry must not carry updated_at"
    assert data["entry_type"] in [t.value for t in LedgerEntryType]
    assert isinstance(data["amount_cents"], int)


def assert_donation(data: dict):
    _assert_common_fields(data, "Donation")
    assert data["status"] in [s.value for s in DonationStatus]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_receipt(data: dict):
    _assert_common_fields(data, "TaxReceipt")
    assert data["status"] in [s.value for s in ReceiptStatus]
    assert isinstance(data["receipt_number"], str) and data["receipt_number"].startswith("FS-")
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["amount_cents"], int)


def assert_disbursement(data: dict):
    _assert_common_fields(data, "DisbursementRequest")
    assert data["status"] in [s.value for s in DisbursementStatus]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["high_value"], bool)
    assert data["payee_type"] in ["VENDOR", "STAFF", "OTHER"]


def assert_engagement(data: dict):
    _assert_common_fields(data, "StaffEngagement")
    assert data["status"] in [s.value for s in EngagementStatus]
    assert data["engagement_type"] in ["EMPLOYEE", "CONTRACTOR"]
    assert isinstance(data["rate_cents"], int)
    assert isinstance(data["requires_1099"], bool)


def assert_review(data: dict):
    _assert_common_fields(data, "ComplianceReview")
    assert data["status"] in [s.value for s in ReviewStatus]
    assert isinstance(data["findings_count"], int)
    assert isinstance(data["open_findings_count"], int)


def assert_incident(data: dict):
    _assert_common_fields(data, "RiskIncident")
    assert data["status"] in [s.value for s in IncidentStatus]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def assert_exit_plan(data: dict):
    _assert_common_fields(data, "ExitPlan")
    assert data["status"] in [s.value for s in ExitPlanStatus]
    assert isinstance(data["signoffs"], list)


def assert_tranche(data: dict):
    _assert_common_fields(data, "GrantTranche")
    assert data["status"] in [s.value for s in TrancheStatus]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["spent_cents"], int)


def assert_fee_assessment(data: dict):
    _assert_common_fields(data, "FeeAssessment")
    assert data["status"] in [s.value for s in FeeAssessmentStatus]
    for field in (
        "provisional_fees_cents", "refund_reversals_cents",
        "annual_platform_fee_cents", "final_fees_cents", "delta_cents",
    ):
        assert isinstance(data[field], int), f"FeeAssessment.{field} must be integer cents"


def assert_fund_conservation(fund: dict):
    """PRD §2.6: available_cents derived from the totals must equal its stored value.

    available = received - refunded - fees_charged + fees_reversed - disbursed
                - transferred_out + adjustments - committed - reserved
    """
    expected = (
        fund["total_received_cents"] - fund["total_refunded_cents"]
        - fund["total_fees_charged_cents"] + fund["total_fees_reversed_cents"]
        - fund["total_disbursed_cents"] - fund["total_transferred_out_cents"]
        + fund["total_adjustments_cents"] - fund["committed_cents"] - fund["reserved_cents"]
    )
    assert fund["available_cents"] == expected, (
        f"Fund conservation violated: available_cents {fund['available_cents']} != {expected} "
        f"recomputed from totals"
    )
