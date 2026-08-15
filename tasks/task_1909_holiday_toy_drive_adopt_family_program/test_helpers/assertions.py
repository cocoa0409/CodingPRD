"""Entity assertions and domain invariant checkers (PRD §2.2-§2.4 shapes)."""
import re

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_CAMPAIGN_STATES = ["DRAFT", "INTAKE_OPEN", "MATCHING", "DISTRIBUTION_PREP",
                    "DISTRIBUTION", "RECONCILIATION", "CLOSED"]
_FAMILY_STATES = ["REFERRED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "MATCHED",
                  "PARTIALLY_FULFILLED", "FULFILLED", "BACKFILLED", "CLOSED",
                  "WITHDRAWN"]
_CHILD_STATES = ["REGISTERED", "WISH_LOCKED", "ADOPTED", "GIFT_RECEIVED",
                 "DELIVERED", "BACKFILL_ELIGIBLE", "BACKFILL_PURCHASED", "CLOSED"]
_WISH_STATES = ["REQUESTED", "APPROVED", "REJECTED", "COMMITTED", "RECEIVED",
                "DELIVERED", "BACKFILL_SOURCED"]
_ADOPTION_STATES = ["PLEDGED", "CONFIRMED", "PARTIALLY_RECEIVED", "FULFILLED",
                    "LATE_CANCELLED", "DONOR_CANCELLED", "ADMIN_CANCELLED",
                    "EXPIRED"]
_GIFT_STATES = ["COMMITTED", "IN_TRANSIT", "RECEIVED", "SORTED", "STAGED",
                "DELIVERED", "RETURNED_TO_DONOR", "BACKFILL_REPLACED"]
_PURCHASE_STATES = ["ORDERED", "PURCHASED", "SORTED", "DELIVERED", "CANCELLED"]
_EVENT_STATES = ["PLANNED", "OPEN_FOR_SLOTS", "SORTING", "LOCKED", "COMPLETED",
                 "CANCELLED"]
_SLOT_STATES = ["RESERVED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"]
_FLAG_STATES = ["OPEN", "CONFIRMED_DUPLICATE", "DISMISSED"]
_NOTE_STATES = ["QUEUED", "SENT", "BOUNCED", "CANCELLED"]
_AGE_BANDS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE", "PRETEEN", "TEEN"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["season_year"], int)
    assert data["status"] in _CAMPAIGN_STATES
    assert data["privacy_mode"] in ("STRICT", "STANDARD")
    assert isinstance(data["backfill_spent_cents"], int)
    assert data["backfill_spent_cents"] >= 0
    assert data["backfill_spent_cents"] <= data["backfill_budget_cents"], \
        "spent backfill budget may never exceed the budget"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["referral_quota"], int) and data["referral_quota"] >= 1


def assert_family(data: dict):
    _assert_common(data)
    assert data["status"] in _FAMILY_STATES
    assert isinstance(data["total_children_count"], int)
    assert isinstance(data["fulfilled_children_count"], int)
    assert 0 <= data["fulfilled_children_count"] <= max(
        data["total_children_count"], data["fulfilled_children_count"])


def assert_child(data: dict):
    _assert_common(data)
    assert data["status"] in _CHILD_STATES
    assert data["age_band"] in _AGE_BANDS
    assert isinstance(data["gift_estimate_cents"], int)
    assert data["gift_estimate_cents"] >= 0


def assert_wish_item(data: dict):
    _assert_common(data)
    assert data["status"] in _WISH_STATES
    assert isinstance(data["estimated_price_cents"], int)
    assert isinstance(data["priority_rank"], int)


def assert_donor(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["giving_history_cents"], int)
    assert data["giving_history_cents"] >= 0


def assert_adoption(data: dict):
    _assert_common(data)
    assert data["status"] in _ADOPTION_STATES
    assert data["scope"] in ("WHOLE_FAMILY", "CHILD_LIST")
    assert isinstance(data["commitment_cents"], int)


def assert_gift(data: dict):
    _assert_common(data)
    assert data["status"] in _GIFT_STATES
    assert isinstance(data["declared_value_cents"], int)
    assert data["declared_value_cents"] >= 0


def assert_backfill_purchase(data: dict):
    _assert_common(data)
    assert data["status"] in _PURCHASE_STATES
    assert isinstance(data["quoted_cost_cents"], int)


def assert_distribution_event(data: dict):
    _assert_common(data)
    assert data["status"] in _EVENT_STATES
    assert isinstance(data["capacity_slots"], int)


def assert_distribution_slot(data: dict):
    _assert_common(data)
    assert data["status"] in _SLOT_STATES
    assert data["lane"] in ("A", "B", "C", "D")
    assert isinstance(data["gifts_staged_count"], int)


def assert_duplicate_flag(data: dict):
    _assert_common(data)
    assert data["status"] in _FLAG_STATES
    assert data["detected_by"] in ("AUTO_HASH", "MANUAL_REPORT")


def assert_thank_you_note(data: dict):
    _assert_common(data)
    assert data["status"] in _NOTE_STATES
    assert data["template"] in ("STANDARD", "MAJOR_DONOR", "FIRST_TIME",
                                "LAPSED_RETURNING")


def assert_audit_event(data: dict):
    """Append-only audit rows carry only id + created_at as common fields
    (PRD §2.4): no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit events have no updated_at"
    assert "version" not in data, "audit events have no version"
    assert data["event_type"] in ("PII_VIEW", "PII_EXPORT", "STATUS_CHANGE",
                                  "DUPLICATE_FLAGGED", "DUPLICATE_RESOLVED",
                                  "CONSENT_CHANGE")


def assert_season_settings(data: dict):
    _assert_common(data)
    assert data["singleton_key"] == "GLOBAL"
    assert isinstance(data["duplicate_auto_detect_enabled"], bool)
    assert isinstance(data["late_donor_grace_hours"], int)
    assert 0 <= data["late_donor_grace_hours"] <= 72
    assert isinstance(data["major_donor_threshold_cents"], int)


def assert_is_sha256_hex(value: str):
    assert isinstance(value, str) and _HEX64.match(value), \
        f"expected a 64-char lowercase hex SHA-256 string, got {value!r}"


def assert_backfill_budget_invariant(campaign: dict):
    """The spent pool never exceeds the declared budget (PRD §3.8)."""
    assert campaign["backfill_spent_cents"] >= 0
    assert campaign["backfill_spent_cents"] <= campaign["backfill_budget_cents"]
