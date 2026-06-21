"""Entity assertions and domain invariant checkers for the Tattoo & Piercing
Studio API. Built on the framework's generic validators.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

ARTIST_DISCIPLINES = ["TATTOO", "PIERCING", "BOTH"]
CLIENT_ID_STATUSES = ["UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "REJECTED"]
FLASH_STATUSES = ["AVAILABLE", "RESERVED", "RETIRED"]
CUSTOM_REQUEST_STATUSES = ["PENDING", "QUOTED", "REVISION_REQUESTED",
                           "APPROVED", "DECLINED", "CONVERTED"]
APPOINTMENT_STATUSES = ["HELD", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"]
DEPOSIT_STATUSES = ["CONFIRMED", "FORFEITED", "APPLIED"]
TOUCHUP_STATUSES = ["REQUESTED", "SCHEDULED", "DENIED"]
PORTFOLIO_VISIBILITIES = ["DRAFT", "PUBLISHED", "HIDDEN"]


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_artist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["discipline"] in ARTIST_DISCIPLINES, f"bad discipline {data['discipline']!r}"
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 1000
    assert 0 < data["commission_pct"] <= 1, f"commission_pct out of range: {data['commission_pct']}"
    assert isinstance(data["accepting_custom"], bool)
    assert isinstance(data["completed_session_count"], int) and data["completed_session_count"] >= 0
    assert isinstance(data["artist_cancel_count"], int) and data["artist_cancel_count"] >= 0
    assert isinstance(data["late_reschedule_count"], int) and data["late_reschedule_count"] >= 0
    assert isinstance(data["reliability_score"], int) and 0 <= data["reliability_score"] <= 100


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["date_of_birth"], str)
    assert data["id_status"] in CLIENT_ID_STATUSES, f"bad id_status {data['id_status']!r}"


def assert_flash_design(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["artist_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["piece_price_cents"], int) and data["piece_price_cents"] >= 1000
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 15
    assert data["status"] in FLASH_STATUSES, f"bad flash status {data['status']!r}"


def assert_custom_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["artist_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["brief"], str)
    assert data["status"] in CUSTOM_REQUEST_STATUSES, f"bad request status {data['status']!r}"


def assert_chair(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["cleanup_buffer_minutes"], int) and data["cleanup_buffer_minutes"] >= 0
    assert isinstance(data["active"], bool)


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["artist_id"])
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["chair_id"])
    assert data["pricing_mode"] in ["HOURLY", "PIECE"]
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 15
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["required_deposit_cents"], int) and data["required_deposit_cents"] >= 0
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0
    assert data["status"] in APPOINTMENT_STATUSES, f"bad appointment status {data['status']!r}"


def assert_deposit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in DEPOSIT_STATUSES, f"bad deposit status {data['status']!r}"


def assert_consent_waiver(data: dict):
    """ConsentWaiver is immutable (common_fields:false): id + created_at only,
    plus its own fields. It MUST NOT carry updated_at or version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "waiver id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["medical_flags"], list)
    assert isinstance(data["aftercare_acknowledged"], bool)
    assert is_iso8601_timestamp(data["signed_at"]), "signed_at must be ISO 8601"


def assert_touchup(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["parent_appointment_id"])
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in TOUCHUP_STATUSES, f"bad touchup status {data['status']!r}"


def assert_portfolio_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["artist_id"])
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["caption"], str)
    assert data["visibility"] in PORTFOLIO_VISIBILITIES, f"bad visibility {data['visibility']!r}"
