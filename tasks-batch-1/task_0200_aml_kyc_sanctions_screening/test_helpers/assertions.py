"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """id + created_at only; NO updated_at, NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not expose version"
    assert "updated_at" not in data, "append-only entity must not expose updated_at"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["customer_type"] in ("INDIVIDUAL", "LEGAL_ENTITY")
    assert data["cdd_status"] in (
        "NEW", "RISK_RATED", "SCREENING_CLEARED", "APPROVED",
        "EDD_REQUIRED", "REJECTED", "OFFBOARDED",
    )
    assert data["risk_rating"] in (None, "LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert isinstance(data["open_hit_count"], int) and data["open_hit_count"] >= 0


def assert_risk_assessment(data: dict):
    assert_common_fields(data)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["risk_band"] in ("LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert isinstance(data["applied"], bool)


def assert_screening_hit(data: dict):
    assert_common_fields(data)
    assert data["list_type"] in ("OFAC_SDN", "EU_SANCTIONS", "PEP", "ADVERSE_MEDIA")
    assert data["disposition"] in ("PENDING", "FALSE_POSITIVE", "ESCALATED", "CONFIRMED")
    assert isinstance(data["is_derogatory"], bool)


def assert_account(data: dict):
    assert_common_fields(data)
    assert data["kyc_status"] in ("PENDING_KYC", "KYC_OK", "KYC_BLOCKED")
    assert data["monitoring_status"] in ("ACTIVE", "UNDER_INVESTIGATION", "FROZEN")
    assert isinstance(data["aggregate_cash_in_cents"], int)
    assert isinstance(data["cumulative_credited_cents"], int)


def assert_transaction(data: dict):
    assert_append_only_fields(data)
    assert data["direction"] in ("CASH_IN", "CASH_OUT", "WIRE_IN", "WIRE_OUT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["triggered_rule"] in (
        None, "STRUCTURING", "RAPID_MOVEMENT", "HIGH_RISK_GEO", "CTR_THRESHOLD",
    )


def assert_alert(data: dict):
    assert_common_fields(data)
    assert data["rule_code"] in (
        "STRUCTURING", "RAPID_MOVEMENT", "HIGH_RISK_GEO", "CTR_THRESHOLD",
    )
    assert data["status"] in ("OPEN", "LINKED", "DISMISSED")
    assert isinstance(data["severity_score"], (int, float))


def assert_case(data: dict):
    assert_common_fields(data)
    assert data["priority"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["disposition"] in (
        "TRIAGE", "INVESTIGATING", "SAR_RECOMMENDED", "CTR_REQUIRED",
        "CLOSED_NO_ACTION", "FILED",
    )
    assert isinstance(data["linked_alert_count"], int)


def assert_filing(data: dict):
    assert_common_fields(data)
    assert data["filing_type"] in ("SAR", "CTR")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_lookback_review(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["total_items"], int)
    assert isinstance(data["cleared_items"], int)
    assert isinstance(data["escalated_items"], int)


def assert_lookback_item(data: dict):
    assert_common_fields(data)
    assert data["item_status"] in ("QUEUED", "CLEARED", "ESCALATED")
