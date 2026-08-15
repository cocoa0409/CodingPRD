"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_iso8601(value: str) -> datetime:
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_iso_instant_equal(actual: str, expected: str):
    """Assert two ISO 8601 UTC timestamps denote the same instant.

    The PRD pins the *instant* (e.g., "reserved_until set to the current logical
    time plus 14 days", "due_date set automatically to period_end plus 90 days")
    and pins a three-fractional-digit format only for created_at/updated_at and
    api_request_timestamp (§2.2, §2.4). Domain timestamps therefore compare as
    parsed instants, not as raw strings.
    """
    assert _parse_iso8601(actual) == _parse_iso8601(expected), (
        f"timestamps differ as instants: {actual!r} != {expected!r}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_fundraiser(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["max_prospect_count"], int) and data["max_prospect_count"] > 0
    assert isinstance(data["max_open_ask_cents"], int) and data["max_open_ask_cents"] > 0
    assert isinstance(data["current_prospect_count"], int) and data["current_prospect_count"] >= 0
    assert isinstance(data["current_open_ask_cents"], int) and data["current_open_ask_cents"] >= 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_prospect(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["prospect_type"] in ["INDIVIDUAL", "ORGANIZATION"]
    assert data["research_status"] in ["IDENTIFIED", "IN_SCREENING", "RATED", "DISQUALIFIED"]
    assert data["moves_stage"] in ["QUALIFICATION", "CULTIVATION", "SOLICITATION", "NEGOTIATION", "STEWARDSHIP", "CLOSED_LOST"]
    assert isinstance(data["lifetime_given_cents"], int) and data["lifetime_given_cents"] >= 0
    assert isinstance(data["outstanding_pledge_cents"], int) and data["outstanding_pledge_cents"] >= 0


def assert_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["assessed_capacity_cents"], int) and data["assessed_capacity_cents"] > 0
    assert data["evidence_tier"] in ["SELF_REPORTED", "PUBLIC_RECORD", "VERIFIED_DOCUMENT"]
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("fundraiser_id", "")), "fundraiser_id must be a UUID"
    assert is_valid_uuid(data.get("prospect_id", "")), "prospect_id must be a UUID"
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_proposal(data: dict):
    _assert_common(data)
    assert data["proposal_type"] in ["OUTRIGHT", "PLEDGE", "PLANNED"]
    assert isinstance(data["ask_amount_cents"], int) and data["ask_amount_cents"] > 0
    assert data["status"] in ["DRAFT", "UNDER_REVIEW", "NEGOTIATING", "RETURNED", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED"]


def assert_naming_opportunity(data: dict):
    _assert_common(data)
    assert data["category"] in ["BUILDING", "ENDOWED_CHAIR", "SCHOLARSHIP", "PROGRAM"]
    assert isinstance(data["price_floor_cents"], int) and data["price_floor_cents"] > 0
    assert data["status"] in ["AVAILABLE", "RESERVED", "OCCUPIED", "RETIRED"]


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["restriction_type"] in ["UNRESTRICTED", "RESTRICTED_CURRENT_USE", "ENDOWED"]
    assert isinstance(data["agreement_amount_cents"], int) and data["agreement_amount_cents"] > 0
    assert data["signature_status"] in ["DRAFT", "PENDING_SIGNATURE", "EXECUTED", "RESCINDED"]
    assert data["compliance_status"] in ["COMPLIANT", "STEWARDSHIP_LAPSED"]


def assert_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["is_endowed"], bool)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["minimum_activation_cents"], int) and data["minimum_activation_cents"] > 0
    assert data["status"] in ["PENDING_MINIMUM", "ACTIVE", "SPENDING_FROZEN", "CLOSED"]


def assert_pledge(data: dict):
    _assert_common(data)
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] > 0
    assert isinstance(data["installment_count"], int) and 1 <= data["installment_count"] <= 120
    assert data["frequency"] in ["MONTHLY", "QUARTERLY", "ANNUAL"]
    assert data["status"] in ["ACTIVE", "FULFILLED", "WRITTEN_OFF", "CANCELLED"]
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0


def assert_installment(data: dict):
    _assert_common(data)
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["written_off_cents"], int) and data["written_off_cents"] >= 0
    assert isinstance(data["reminder_count"], int) and 0 <= data["reminder_count"] <= 3
    assert data["status"] in ["SCHEDULED", "REMINDED", "OVERDUE", "PAID", "WRITTEN_OFF"]


def assert_write_off(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["reason"] in ["UNCOLLECTIBLE", "DONOR_HARDSHIP", "DUPLICATE", "OTHER"]
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]


def assert_gift_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payment_method"] in ["CHECK", "WIRE", "CARD", "STOCK"]
    assert isinstance(data["reversed"], bool)


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["goal_cents"], int) and data["goal_cents"] > 0
    assert isinstance(data["face_value_counted_cents"], int)
    assert isinstance(data["cash_counted_cents"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED", "REPORTED"]


def assert_credit_split(data: dict):
    _assert_common(data)
    assert data["credit_type"] in ["HARD", "SOFT"]
    assert isinstance(data["split_pct"], int) and 1 <= data["split_pct"] <= 100
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_stewardship_report(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert is_iso8601_timestamp(data.get("due_date", "")), "due_date must be ISO 8601"
    assert data["status"] in ["DRAFT", "SUBMITTED", "DELIVERED", "OVERDUE"]


def assert_recognition_society(data: dict):
    _assert_common(data)
    assert data["level"] in ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["threshold_cash_cents"], int) and data["threshold_cash_cents"] > 0
