"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3).

Version assertions are always relative: the PRD pins "increments by exactly
one on every mutation" (§2.4) but never pins the initial value, so tests
compare a fresh read against a previously observed version.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ITEM_TERMINAL_STATES,
    OCCUPYING_STATES,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str):
    """Two ISO 8601 representations of the same instant compare equal."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"expected instant {expected_iso}, got {actual}"
    )


def assert_version_bumped_once(before: int, after: int, what: str = "resource"):
    """PRD §2.4: version 'increments by exactly one on every mutation'."""
    assert after == before + 1, (
        f"{what} version must increment by exactly one: {before} -> {after}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["program_type"] in ("TRANSIT", "FACILITY")
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["active"], bool)


def assert_retention_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["item_category"] in (
        "ELECTRONICS", "JEWELRY", "ID_DOCUMENT", "KEYS", "CLOTHING",
        "BAG", "WALLET", "BICYCLE", "CASH", "OTHER",
    )
    assert data["value_tier"] in ("LOW", "MID", "HIGH")
    assert isinstance(data["retention_days"], int) and data["retention_days"] >= 1
    assert data["disposal_method"] in ("AUCTION", "DESTRUCTION", "DONATION")
    assert isinstance(data["active"], bool)


def assert_storage_location(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert isinstance(data["supports_high_value"], bool)
    assert isinstance(data["active"], bool)
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0


def assert_venue(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    assert isinstance(data["insurance_cap_cents"], int) and data["insurance_cap_cents"] >= 0


def assert_claimant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert isinstance(data["id_verified"], bool)


def assert_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("storage_location_id", ""))
    assert data["category"] in (
        "ELECTRONICS", "JEWELRY", "ID_DOCUMENT", "KEYS", "CLOTHING",
        "BAG", "WALLET", "BICYCLE", "CASH", "OTHER",
    )
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert data["value_tier"] in ("LOW", "MID", "HIGH")
    assert isinstance(data["is_identification"], bool)
    assert data["is_identification"] is (data["category"] == "ID_DOCUMENT")
    assert isinstance(data["description"], str)
    assert isinstance(data["found_at"], str)
    assert isinstance(data["found_location"], str)
    assert is_valid_uuid(data.get("retention_policy_id", ""))
    assert isinstance(data["retention_deadline"], str)
    assert data["status"] in (
        "STORED", "LISTED", "RELEASE_PENDING", "RELEASED", "REFERRED_TO_LE",
        "IN_LE_CUSTODY", "EVIDENCE", "AUCTION_ELIGIBLE", "LOTTED", "SOLD",
        "DISPOSAL_PENDING", "DISPOSED", "DONATED",
    )
    assert isinstance(data["unsold_count"], int) and data["unsold_count"] >= 0
    assert data.get("pending_disposal_method") in (None, "AUCTION", "DESTRUCTION", "DONATION")
    assert isinstance(data["intake_officer_id"], str) and data["intake_officer_id"]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert is_valid_uuid(data.get("claimant_id", ""))
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "STAYED",
        "APPROVED", "REJECTED", "WITHDRAWN", "RELEASED",
    )
    assert isinstance(data["proof_serial"], bool)
    assert isinstance(data["proof_photo"], bool)
    assert isinstance(data["proof_receipt"], bool)
    assert data["proof_description_detail"] in ("BRIEF", "DETAILED")
    assert isinstance(data["proof_score"], int) and 0 <= data["proof_score"] <= 100


def assert_inquiry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["subject"], str)
    assert isinstance(data["message"], str)
    assert data["status"] in ("OPEN", "ANSWERED", "CLOSED")
    assert isinstance(data["sla_deadline"], str)


def assert_auction_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["name"], str)
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_auction_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["title"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SOLD", "CLOSED_UNSOLD", "CANCELLED")
    assert isinstance(data["minimum_bid_cents"], int) and data["minimum_bid_cents"] >= 0
    assert isinstance(data["created_by"], str) and data["created_by"]


def assert_lot_item(data: dict):
    """Append-only membership row: id + created_at, NO updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lot-item rows carry no updated_at"
    assert "version" not in data, "lot-item rows carry no version"
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["floor_price_cents"], int) and data["floor_price_cents"] >= 0


def assert_referral_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["status"] in ("REFERRED", "IN_CUSTODY", "RETURNED", "CONVERTED_TO_EVIDENCE")
    assert isinstance(data["referred_by"], str) and data["referred_by"]


def assert_release_record(data: dict):
    """Append-only release record: id + created_at, NO updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "release records carry no updated_at"
    assert "version" not in data, "release records carry no version"
    assert is_valid_uuid(data.get("item_id", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["released_by"], str) and data["released_by"]
    assert data["handover_method"] in ("IN_PERSON", "MAIL")
    assert isinstance(data["id_document_ref"], str)
    assert isinstance(data["released_at"], str)


def assert_occupancy_invariant(location: dict, items_in_occupying_states: int):
    """PRD §2.9: occupied_slots equals the count of items at the location whose
    status is in the occupying set."""
    assert location["occupied_slots"] == items_in_occupying_states, (
        f"occupied_slots {location['occupied_slots']} != expected "
        f"{items_in_occupying_states} (occupying states: {sorted(OCCUPYING_STATES)}; "
        f"IN_LE_CUSTODY and terminal states {sorted(ITEM_TERMINAL_STATES)} do not occupy)"
    )
