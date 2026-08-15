"""Entity assertions and domain invariant checkers.

Structural assertions only: identity/timestamp typing, status-enum membership,
and integer money fields. Computed-field values are asserted by the tests that
own the corresponding PRD rule.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssessmentStatus,
    DisputeStatus,
    ElectionStatus,
    LedgerEntryType,
    LineStatus,
    LocalStatus,
    MemberStatus,
    NoticeStatus,
    ObjectorCaseStatus,
    PerCapitaReportStatus,
    RemittanceStatus,
    TransferStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_immutable_record_fields(data: dict):
    """Immutable records carry only id + created_at among the common fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def assert_local(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in LocalStatus]
    assert data["dues_method"] in ("PERCENTAGE_OF_GROSS", "FLAT_RATE")
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "default_dues_percent_bp",
        "default_flat_dues_cents",
        "per_capita_rate_cents",
        "delinquency_threshold_cents",
        "grace_periods",
        "notice_cure_days",
        "reinstatement_base_fee_cents",
        "max_suspensions",
        "expel_after_months",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_classification(data: dict):
    _assert_common_fields(data)
    assert data["code"] in ("JOURNEYMAN", "APPRENTICE", "PROBATIONARY", "RETIREE")
    assert isinstance(data["local_id"], str) and data["local_id"]
    assert isinstance(data["min_monthly_dues_cents"], int)


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_member(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in MemberStatus]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["member_number"], str) and data["member_number"]
    assert isinstance(data["local_id"], str) and data["local_id"]
    assert isinstance(data["classification_id"], str) and data["classification_id"]
    assert isinstance(data["arrears_cents"], int) and data["arrears_cents"] >= 0
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0
    assert isinstance(data["suspension_count"], int) and data["suspension_count"] >= 0
    assert isinstance(data["good_standing"], bool)


def assert_member_money_consistency(data: dict):
    """The derived pair must always be mutually consistent with a signed balance."""
    assert isinstance(data["arrears_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert not (data["arrears_cents"] > 0 and data["credit_balance_cents"] > 0), (
        "arrears and credit balance can never both be positive"
    )


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in AssessmentStatus]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["gross_wages_cents"], int)
    assert isinstance(data["assessed_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["min_applied_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_immutable_record_fields(data)
    assert data["entry_type"] in [t.value for t in LedgerEntryType]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7


def assert_remittance(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RemittanceStatus]
    assert data["dispute_status"] in [s.value for s in DisputeStatus]
    assert isinstance(data["employer_id"], str) and data["employer_id"]
    assert isinstance(data["local_id"], str) and data["local_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["remitted_cents"], int)
    assert isinstance(data["received_by_user_id"], str)


def assert_remittance_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["remittance_id"], str) and data["remittance_id"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["deducted_cents"], int)
    assert isinstance(data["gross_wages_cents"], int)
    if data.get("line_status") is not None:
        assert data["line_status"] in [s.value for s in LineStatus]


def assert_notice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in NoticeStatus]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["arrears_at_notice_cents"], int)


def assert_objector_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ObjectorCaseStatus]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["cumulative_rebate_cents"], int)


def assert_transfer(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in TransferStatus]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["from_local_id"], str) and data["from_local_id"]
    assert isinstance(data["to_local_id"], str) and data["to_local_id"]
    assert isinstance(data["effective_period"], str) and len(data["effective_period"]) == 7


def assert_percapita_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PerCapitaReportStatus]
    assert isinstance(data["local_id"], str) and data["local_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert isinstance(data["rate_cents"], int)
    assert isinstance(data["tax_due_cents"], int)
    assert data["tax_due_cents"] == data["member_count"] * data["rate_cents"], (
        "tax_due_cents must equal member_count x rate_cents"
    )


def assert_election(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ElectionStatus]
    assert isinstance(data["local_id"], str) and data["local_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["required_good_standing_months"], int)


def assert_election_eligibility(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["election_id"], str) and data["election_id"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["eligible"], bool)
    assert isinstance(data["ineligibility_reasons"], list)
    assert isinstance(data["arrears_at_freeze_cents"], int)
    assert (len(data["ineligibility_reasons"]) == 0) == data["eligible"], (
        "ineligibility_reasons must be empty exactly when the member is eligible"
    )


def assert_assessment_run(data: dict):
    _assert_immutable_record_fields(data)
    assert isinstance(data["local_id"], str) and data["local_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["assessments_created_count"], int)
    assert isinstance(data["assessments_finalized_count"], int)
