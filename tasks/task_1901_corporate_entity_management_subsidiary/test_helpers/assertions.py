"""Entity assertions and domain invariant checkers.

Each assert_* verifies the PRD-declared field presence/types for one resource,
including the common fields (id UUID, ISO 8601 created_at/updated_at, integer
version) from PRD 2.4. ComplianceEvent is the PRD 2.4 append-only exception:
only id + created_at.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_legal_entity(data: dict):
    _assert_common_fields(data, "LegalEntity")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["entity_type"] in [
        "CORPORATION",
        "LLC",
        "LIMITED_PARTNERSHIP",
        "NONPROFIT_CORPORATION",
    ]
    assert is_valid_uuid(data["formation_jurisdiction_id"])
    assert isinstance(data["formation_date"], str)
    assert isinstance(data["fiscal_year_end_month"], int)
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert isinstance(data["authorized_shares"], int)
    assert data["status"] in [
        "DRAFT",
        "FORMATION_PENDING",
        "ACTIVE",
        "DISSOLUTION_PENDING",
        "DISSOLVED",
    ]
    assert data["compliance_posture"] in [
        "GOOD_STANDING",
        "DELINQUENT",
        "SUSPENDED",
        "FORFEITED",
    ]
    assert isinstance(data["fees_accrued_cents"], int)


def assert_jurisdiction(data: dict):
    _assert_common_fields(data, "Jurisdiction")
    assert isinstance(data["code"], str) and data["code"]
    assert data["annual_report_due_rule"] in ["FIXED_MONTH_DAY", "FORMATION_ANNIVERSARY"]
    assert data["franchise_tax_method"] in ["SHARES_TIERED", "FLAT", "NONE"]
    assert data["penalty_day_counting"] in ["CALENDAR_DAYS", "BUSINESS_DAYS"]
    assert isinstance(data["grace_period_days"], int) and data["grace_period_days"] >= 0
    assert isinstance(data["report_fee_cents"], int)
    assert isinstance(data["cert_fee_cents"], int)


def assert_registered_agent(data: dict):
    _assert_common_fields(data, "RegisteredAgent")
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["address"], str)


def assert_officer(data: dict):
    _assert_common_fields(data, "Officer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in ["ACTIVE", "DEACTIVATED"]


def assert_agent_appointment(data: dict):
    _assert_common_fields(data, "AgentAppointment")
    assert is_valid_uuid(data["entity_id"])
    assert is_valid_uuid(data["agent_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["start_date"], str)
    assert data["status"] in ["ACTIVE", "NOTICE_PENDING", "RESIGNED"]


def assert_resolution(data: dict):
    _assert_common_fields(data, "Resolution")
    assert is_valid_uuid(data["entity_id"])
    assert data["resolution_type"] in [
        "AUTHORIZE_FORMATION",
        "AUTHORIZE_DISSOLUTION",
        "REVOKE_DISSOLUTION",
        "AUTHORIZE_QUALIFICATION",
        "AUTHORIZE_WITHDRAWAL",
        "APPOINT_OFFICER",
        "REMOVE_OFFICER",
        "ACCEPT_RESIGNATION",
        "GRANT_SIGNATURE_AUTHORITY",
        "REVOKE_SIGNATURE_AUTHORITY",
    ]
    assert isinstance(data["payload"], dict)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["drafted_by_user_id"], str)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "ADOPTED",
        "EFFECTIVE",
        "WITHDRAWN",
        "RESCINDED",
    ]


def assert_officer_appointment(data: dict):
    _assert_common_fields(data, "OfficerAppointment")
    assert is_valid_uuid(data["entity_id"])
    assert is_valid_uuid(data["officer_id"])
    assert is_valid_uuid(data["resolution_id"])
    assert data["office_title"] in [
        "PRESIDENT",
        "SECRETARY",
        "TREASURER",
        "CEO",
        "CFO",
        "DIRECTOR",
    ]
    assert data["status"] in ["APPOINTED", "RESIGNED", "REMOVED"]


def assert_annual_filing(data: dict):
    _assert_common_fields(data, "AnnualFiling")
    assert is_valid_uuid(data["entity_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["filing_type"] in ["ANNUAL_REPORT", "FRANCHISE_TAX"]
    assert isinstance(data["period_year"], int)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["report_fee_cents"], int)
    assert data["status"] in [
        "SCHEDULED",
        "PREPARED",
        "OVERDUE",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED",
        "WITHDRAWN",
    ]


def assert_foreign_qualification(data: dict):
    _assert_common_fields(data, "ForeignQualification")
    assert is_valid_uuid(data["entity_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert is_valid_uuid(data["agent_appointment_id"])
    assert data["status"] in [
        "PENDING",
        "QUALIFIED",
        "WITHDRAWAL_PENDING",
        "WITHDRAWN",
        "REVOKED",
    ]


def assert_signature_grant(data: dict):
    _assert_common_fields(data, "SignatureAuthorityGrant")
    assert is_valid_uuid(data["entity_id"])
    assert is_valid_uuid(data["officer_id"])
    assert data["scope"] in ["BANKING", "CONTRACTS", "TAX_FILINGS", "GOVERNMENT_FILINGS"]
    assert isinstance(data["max_amount_cents"], int) and data["max_amount_cents"] > 0
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["expiry_date"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED"]


def assert_certificate(data: dict):
    _assert_common_fields(data, "GoodStandingCertificate")
    assert is_valid_uuid(data["entity_id"])
    assert is_valid_uuid(data["jurisdiction_id"])
    assert data["delivery_speed"] in ["STANDARD", "EXPEDITED"]
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ["REQUESTED", "ISSUED", "DENIED", "EXPIRED"]


def assert_ownership_record(data: dict):
    _assert_common_fields(data, "OwnershipRecord")
    assert is_valid_uuid(data["parent_entity_id"])
    assert is_valid_uuid(data["subsidiary_entity_id"])
    assert isinstance(data["percentage_bps"], int)
    assert 1 <= data["percentage_bps"] <= 10000
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "VOIDED"]


def assert_compliance_event(data: dict):
    """Append-only audit record: only id + created_at as common fields (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ComplianceEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ComplianceEvent.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ComplianceEvent must not carry updated_at"
    assert "version" not in data, "ComplianceEvent must not carry version"
    assert is_valid_uuid(data["entity_id"])
    assert data["event_type"] in [
        "POSTURE_CHANGED",
        "FILING_OVERDUE",
        "FILING_WITHDRAWN",
        "QUALIFICATION_REVOKED",
        "GRANT_REVOKED",
        "CERTIFICATE_DENIED",
        "OFFICER_REMOVED",
        "OFFICER_RESIGNED",
        "AGENT_RESIGNED",
        "DISSOLUTION_COMMENCED",
        "DISSOLUTION_COMPLETED",
        "RESOLUTION_EFFECTIVE_BLOCKED",
    ]
    assert is_iso8601_timestamp(data["occurred_at"])
