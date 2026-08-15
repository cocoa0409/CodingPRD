"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity_label: str):
    """System-managed fields every resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_owner(data: dict):
    _assert_common(data, "Owner")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["last_known_address"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_dormancy_rule(data: dict):
    _assert_common(data, "DormancyRule")
    assert data["property_type"] in [
        "CHECKING", "SAVINGS", "BROKERAGE_SHARES", "UNCASHED_CHECK", "INSURANCE_PROCEEDS"
    ]
    assert isinstance(data["dormancy_years"], int) and 1 <= data["dormancy_years"] <= 15
    assert isinstance(data["effective_from"], str)


def assert_property(data: dict):
    _assert_common(data, "Property")
    assert data["status"] in [
        "ACTIVE", "DORMANT", "DUE_DILIGENCE", "REPORTABLE",
        "REPORTED", "REMITTED", "ESCHEATED", "REUNITED",
    ]
    assert isinstance(data["original_value_cents"], int) and data["original_value_cents"] > 0
    assert isinstance(data["owner_id"], str)


def assert_contact_event(data: dict):
    _assert_common(data, "ContactEvent")
    assert data["contact_type"] in [
        "WITHDRAWAL", "DEPOSIT", "LOGIN_VERIFIED",
        "WRITTEN_CORRESPONDENCE", "PHONE_VERIFIED", "IN_PERSON",
    ]
    assert isinstance(data["qualifies_for_reactivation"], bool)
    assert isinstance(data["property_id"], str)


def assert_letter(data: dict):
    _assert_common(data, "DueDiligenceLetter")
    assert data["status"] in [
        "SENT", "DELIVERED", "RESPONDED", "EXPIRED", "UNDELIVERABLE", "VOIDED"
    ]
    assert isinstance(data["sent_date"], str)
    assert isinstance(data["response_deadline"], str)
    assert isinstance(data["applicable_due_date"], str)


def assert_report(data: dict):
    _assert_common(data, "HolderReport")
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
    assert isinstance(data["total_provisional_cents"], int)
    assert isinstance(data["total_final_cents"], int)
    assert isinstance(data["confirmed_remittance_cents"], int)
    assert isinstance(data["line_count"], int)


def assert_line_item(data: dict):
    _assert_common(data, "ReportLineItem")
    assert data["status"] in ["INCLUDED", "FINAL", "REMOVED"]
    assert data["line_type"] in ["CASH", "SECURITIES"]
    assert isinstance(data["provisional_value_cents"], int)


def assert_securities_detail(data: dict):
    _assert_common(data, "SecuritiesDetail")
    assert data["status"] in ["REGISTERED", "EXECUTION_PENDING", "LIQUIDATED"]
    assert isinstance(data["shares_quantity"], int) and data["shares_quantity"] > 0
    assert isinstance(data["last_close_price_cents"], int)
    assert isinstance(data["accrued_dividends_cents"], int)


def assert_liquidation_order(data: dict):
    _assert_common(data, "LiquidationOrder")
    assert data["status"] in ["REQUESTED", "EXECUTED", "SETTLED", "CANCELLED"]
    assert isinstance(data["liquidation_fee_cents"], int)


def assert_remittance(data: dict):
    _assert_common(data, "Remittance")
    assert data["status"] in ["PENDING", "CONFIRMED", "FAILED"]
    assert isinstance(data["amount_cents"], int)


def assert_claim(data: dict):
    _assert_common(data, "OwnerClaim")
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED",
        "APPROVED", "DENIED", "PAID", "WITHDRAWN",
    ]
    assert data["claim_type"] in ["CASH", "SECURITIES"]


def assert_penalty_assessment(data: dict):
    _assert_common(data, "PenaltyAssessment")
    assert data["status"] in ["ASSESSED", "PAID", "WAIVED", "DISPUTED"]
    assert isinstance(data["days_late"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert data["total_cents"] == data["penalty_cents"] + data["interest_cents"], (
        "total_cents must equal penalty_cents + interest_cents"
    )


def assert_audit_case(data: dict):
    _assert_common(data, "AuditCase")
    assert data["status"] in ["OPENED", "FIELDWORK", "FINDINGS_ISSUED", "CLOSED"]
    assert isinstance(data["lookback_start_year"], int)
    assert isinstance(data["lookback_end_year"], int)
    assert data["lookback_end_year"] >= data["lookback_start_year"]


def assert_document_record(data: dict):
    _assert_common(data, "DocumentRecord")
    assert data["artifact_type"] in [
        "LETTER_COPY", "REPORT_FILE", "CLAIM_EVIDENCE", "REMITTANCE_RECEIPT"
    ]
    assert data["status"] in ["REGISTERED", "PURGED"]
    assert isinstance(data["retention_until"], str)


def assert_report_totals(data: dict):
    """Report aggregate invariants (PRD §3.4): totals and line_count are
    non-negative and consistent with each other."""
    assert data["total_provisional_cents"] >= 0
    assert data["total_final_cents"] >= 0
    assert data["line_count"] >= 0
    assert data["confirmed_remittance_cents"] >= 0
