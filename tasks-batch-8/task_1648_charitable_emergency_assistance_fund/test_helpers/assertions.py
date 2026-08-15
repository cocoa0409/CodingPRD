"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Timestamp comparisons against the logical
clock are made as parsed instants (PRD §2.5 pins ISO 8601 UTC format, not a
specific fractional-digit rendering of a given instant).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_clock_instant(value: str, expected_iso: str) -> None:
    """Assert a recorded timestamp names the same instant as the logical clock
    reading `expected_iso`, regardless of fractional-digit rendering."""
    assert _parse_instant(value) == _parse_instant(expected_iso), (
        f"expected instant {expected_iso}, got {value}"
    )


def _assert_common_fields(data: dict, with_version: bool = True) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )
    else:
        # Append-only ledgers (PRD §2.5): updated_at and version are absent.
        assert "updated_at" not in data, "append-only record must not carry updated_at"
        assert "version" not in data, "append-only record must not carry version"


def assert_household(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["head_of_household_name"], str) and data["head_of_household_name"]
    assert isinstance(data["address"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0


def assert_policy(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["max_annual_benefit_cents"], int) and data["max_annual_benefit_cents"] > 0
    assert isinstance(data["rent_cap_cents"], int) and data["rent_cap_cents"] > 0
    assert isinstance(data["utility_cap_cents"], int) and data["utility_cap_cents"] > 0
    assert isinstance(data["income_limit_cents"], int) and data["income_limit_cents"] >= 0
    assert isinstance(data["appeal_window_days"], int) and data["appeal_window_days"] > 0
    assert isinstance(data["require_eviction_notice"], bool)
    assert isinstance(data["require_lease_ledger"], bool)
    assert isinstance(data["require_utility_bill"], bool)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_vendor(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["vendor_type"] in ("LANDLORD", "UTILITY")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_application(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("household_id", "")), "household_id must be a UUID"
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert data["category"] in ("RENT", "UTILITY")
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert isinstance(data["service_month"], str) and len(data["service_month"]) == 7
    assert isinstance(data["intake_caseworker_id"], str) and data["intake_caseworker_id"]
    assert data["status"] in (
        "INTAKE", "SUBMITTED", "UNDER_VERIFICATION", "VERIFICATION_FAILED",
        "PENDING_DECISION", "WAITLISTED", "APPROVED", "PAID", "DENIED",
        "WITHDRAWN", "CLOSED",
    )


def assert_document(data: dict) -> None:
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data["doc_type"] in ("EVICTION_NOTICE", "LEASE_LEDGER", "UTILITY_BILL", "ID_VERIFICATION")
    assert isinstance(data["file_reference"], str) and data["file_reference"]
    assert isinstance(data["uploaded_by"], str) and data["uploaded_by"]


def assert_verification(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert isinstance(data["verifier_id"], str) and data["verifier_id"]
    assert data["status"] in ("PENDING", "PASSED", "FAILED", "SUPERSEDED")


def assert_duplication_check(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]
    assert data["status"] in ("PENDING", "CLEARED", "FLAGGED", "SUPERSEDED")


def assert_award(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert is_valid_uuid(data.get("policy_id", "")), "policy_id must be a UUID"
    assert isinstance(data["awarded_amount_cents"], int) and data["awarded_amount_cents"] > 0
    assert isinstance(data["benefit_year"], int) and 1900 < data["benefit_year"] < 2200
    assert data["status"] in ("ACTIVE", "PARTIALLY_DISBURSED", "DISBURSED", "VOIDED")


def assert_allocation(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", "")), "award_id must be a UUID"
    assert is_valid_uuid(data.get("funding_source_id", "")), "funding_source_id must be a UUID"
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert isinstance(data["consumed_cents"], int) and data["consumed_cents"] >= 0
    assert data["consumed_cents"] <= data["allocated_cents"], (
        f"consumed_cents {data['consumed_cents']} exceeds allocated_cents {data['allocated_cents']}"
    )
    assert isinstance(data["rank_order"], int) and data["rank_order"] >= 0
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")


def assert_funding_source(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["funder_name"], str) and data["funder_name"]
    assert data["source_type"] in ("DONOR_UNRESTRICTED", "GRANT_RESTRICTED", "GOVERNMENT")
    assert isinstance(data["allowed_categories"], list) and len(data["allowed_categories"]) >= 1
    assert set(data["allowed_categories"]) <= {"RENT", "UTILITY"}
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] > 0
    assert isinstance(data["max_per_household_cents"], int) and data["max_per_household_cents"] > 0
    assert isinstance(data["reserved_cents"], int) and data["reserved_cents"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert isinstance(data["available_cents"], int)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "CLOSED")


def assert_source_balance_invariant(data: dict) -> None:
    """PRD §3.1 invariant: committed + reserved + available == total_budget."""
    total = data["committed_cents"] + data["reserved_cents"] + data["available_cents"]
    assert total == data["total_budget_cents"], (
        f"balance partition broken: committed {data['committed_cents']} + reserved "
        f"{data['reserved_cents']} + available {data['available_cents']} "
        f"!= total_budget {data['total_budget_cents']}"
    )


def assert_payment(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", "")), "award_id must be a UUID"
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert is_valid_uuid(data.get("funding_source_id", "")), "funding_source_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("payment_date", "")), "payment_date must be ISO 8601"
    assert data["status"] in ("ISSUED", "CLEARED", "FAILED", "VOIDED")
    assert isinstance(data["issued_by"], str) and data["issued_by"]


def assert_case_note(data: dict) -> None:
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["author_id"], str) and data["author_id"]
    assert data["note_type"] in ("GENERAL", "FOLLOW_UP", "DUPLICATION_CHECK", "COMMUNICATION")
    assert isinstance(data["body"], str) and data["body"]
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_replenishment_run(data: dict) -> None:
    _assert_common_fields(data, with_version=False)
    assert isinstance(data["run_by"], str) and data["run_by"]
    assert isinstance(data["promoted_count"], int) and data["promoted_count"] >= 0
    assert isinstance(data["denied_count"], int) and data["denied_count"] >= 0
    assert isinstance(data["remaining_waitlisted_count"], int) and data["remaining_waitlisted_count"] >= 0
    assert isinstance(data["promoted_application_ids"], list)
    assert isinstance(data["denied_application_ids"], list)
