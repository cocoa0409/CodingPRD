"""Entity assertions and domain invariant checkers.

PRD §2.4: entities other than EligibleItemCategory and SystemClock carry
id + created_at + updated_at + version. The lighter entities carry only
id + created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ─── Common-fields helpers ─────────────────────────────────────────────

def assert_common_fields(data: dict):
    """Asserts id (UUID), created_at, updated_at (ISO 8601), version (int >= 1).
    Apply to every entity declared in PRD §2.4's first category."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_lighter_fields(data: dict):
    """For EligibleItemCategory and SystemClock — id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ─── Per-entity assertions ─────────────────────────────────────────────

def assert_household(data: dict):
    assert_common_fields(data)
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0
    assert data["state_code"] in (
        "CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI")
    assert isinstance(data["address_line"], str)
    assert isinstance(data["size"], int) and data["size"] >= 0
    assert isinstance(data["gross_income_cents"], int) and data["gross_income_cents"] >= 0
    assert isinstance(data["net_income_cents"], int) and data["net_income_cents"] >= 0
    assert data["status"] in (
        "PENDING", "CERTIFIED", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["heap_recipient"], bool)


def assert_household_member(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["relationship"] in ("HEAD", "SPOUSE", "CHILD", "PARENT", "OTHER")
    assert isinstance(data["monthly_earned_income_cents"], int)
    assert data["monthly_earned_income_cents"] >= 0
    assert isinstance(data["monthly_unearned_income_cents"], int)
    assert data["monthly_unearned_income_cents"] >= 0
    assert isinstance(data["disabled"], bool)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_application(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "DENIED", "EXPIRED")


def assert_ebt_card(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert data["status"] in (
        "PENDING_ISSUE", "ACTIVE", "SUSPENDED", "REPLACED", "CANCELLED")
    # pan_last4 is minted on activate; before that it can be null/empty
    if data.get("pan_last4"):
        assert isinstance(data["pan_last4"], str) and len(data["pan_last4"]) == 4
        assert data["pan_last4"].isdigit()


def assert_monthly_allotment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["benefit_month"], str)
    assert isinstance(data["standard_allotment_cents"], int)
    assert data["standard_allotment_cents"] >= 0
    assert isinstance(data["emergency_supplement_cents"], int)
    assert data["emergency_supplement_cents"] >= 0
    assert isinstance(data["issued_total_cents"], int)
    assert data["issued_total_cents"] >= 0
    assert data["status"] in ("DRAFT", "ISSUED", "EXPUNGED", "ADJUSTED")


def assert_eligible_item_category(data: dict):
    """PRD §2.4: id + created_at only. No updated_at, no version."""
    assert_lighter_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["eligible"], bool)


def assert_purchase_transaction(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["ebt_card_id"])
    assert is_valid_uuid(data["household_id"])
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["line_items"], list)
    assert isinstance(data["ineligible_line_codes"], list)
    assert data["status"] in ("AUTHORIZED", "SETTLED", "REVERSED")


def assert_fraud_flag(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["household_id"])
    assert data["trigger_rule"] in (
        "VELOCITY_SPIKE", "OUT_OF_STATE", "DUPLICATE_HH_MEMBER", "CARD_REPLACE_ABUSE")
    assert data["status"] in (
        "OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")


def assert_abawd_waiver(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["household_member_id"])
    assert isinstance(data["quarter"], str)
    assert isinstance(data["county_unemployment_pct"], (int, float))
    assert 0.0 <= float(data["county_unemployment_pct"]) <= 50.0
    assert isinstance(data["monthly_work_hours"], int)
    assert data["monthly_work_hours"] >= 0
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "REVOKED")


def assert_emergency_allotment_proclamation(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["benefit_month"], str)
    assert isinstance(data["min_supplement_cents"], int)
    assert data["min_supplement_cents"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")


def assert_system_clock(data: dict):
    """PRD §2.4: SystemClock carries only id + created_at."""
    assert_lighter_fields(data)
    assert is_iso8601_timestamp(data.get("current_utc", "")), \
        f"current_utc must be ISO 8601, got {data.get('current_utc')!r}"


# ─── Domain invariants ─────────────────────────────────────────────────

def assert_no_version_field_for_lighter_entity(data: dict):
    """PRD §2.4: EligibleItemCategory / SystemClock have no version / updated_at."""
    assert "version" not in data, \
        f"PRD §2.4: lighter entity must not expose 'version', got {data.get('version')!r}"
    assert "updated_at" not in data, \
        f"PRD §2.4: lighter entity must not expose 'updated_at', got {data.get('updated_at')!r}"
