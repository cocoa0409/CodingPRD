"""Entity assertions and domain invariant checkers for the Bridal Beauty API."""
from datetime import datetime, timezone
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def same_instant(actual: str, expected: str) -> bool:
    """Compare two ISO 8601 UTC timestamps by instant, tolerant of the optional
    three-fractional-digit form (PRD §2.6) — e.g. '...10:30:00Z' == '...10:30:00.000Z'."""
    def parse(s: str) -> datetime:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    return parse(actual) == parse(expected)


# ─── Common-field helpers ─────────────────────────────
def _assert_common_fields(data: dict):
    """id/created_at/updated_at/version — carried by every entity except Payment."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


# ─── Per-entity assertions ────────────────────────────
def assert_artist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["skill_tier"] in ("LEAD", "SENIOR", "JUNIOR")
    assert isinstance(data["hair_rate_per_face_cents"], int) and data["hair_rate_per_face_cents"] >= 0
    assert isinstance(data["makeup_rate_per_face_cents"], int) and data["makeup_rate_per_face_cents"] >= 0
    assert isinstance(data["travel_rate_per_km_cents"], int) and data["travel_rate_per_km_cents"] >= 0
    assert isinstance(data["max_faces_per_hour"], int) and data["max_faces_per_hour"] >= 1
    assert isinstance(data["can_assist"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["portfolio_published"], bool)


def assert_portfolio_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["artist_id"])
    assert isinstance(data["look_name"], str) and len(data["look_name"]) > 0
    assert data["category"] in ("HAIR", "MAKEUP", "BOTH")
    assert data["status"] in ("DRAFT", "PUBLISHED")


def assert_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str) and len(data["client_id"]) > 0
    assert isinstance(data["party_size"], int) and data["party_size"] >= 0
    assert data["status"] in (
        "DRAFT", "QUOTED", "REVISION_REQUESTED", "CONTRACTED",
        "SCHEDULED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["quote_revision"], int) and data["quote_revision"] >= 0
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["trial_required"], bool)


def assert_face(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["person_label"], str) and len(data["person_label"]) > 0
    assert data["service_type"] in ("HAIR", "MAKEUP", "BOTH")
    assert isinstance(data["is_bride"], bool)
    assert data["status"] in ("PENDING", "CONFIRMED", "REMOVED", "SERVICED")


def assert_trial(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["artist_id"])
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["status"] in ("BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["trial_fee_cents"], int) and data["trial_fee_cents"] >= 0


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["lead_artist_id"])
    assert isinstance(data["contracted_total_cents"], int) and data["contracted_total_cents"] >= 0
    assert isinstance(data["deposit_due_cents"], int) and data["deposit_due_cents"] >= 0
    assert data["status"] in ("DRAFT", "SIGNED", "VOIDED")


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["artist_id"])
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert isinstance(data["faces_committed"], int) and data["faces_committed"] >= 0
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_addon(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["assignment_id"])
    assert data["addon_type"] in ("TOUCH_UP", "EXTENDED_STAY")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("APPLIED", "REVERSED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["deposit_amount_cents"], int) and data["deposit_amount_cents"] >= 0
    assert isinstance(data["balance_amount_cents"], int) and data["balance_amount_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert data["deposit_status"] in ("DUE", "PAID", "REFUNDED", "FORFEITED")
    assert data["balance_status"] in ("NOT_DUE", "DUE", "PAID", "WRITTEN_OFF")


def assert_cancellation_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["event_id"])
    assert data["reason"] in ("CLIENT_CHOICE", "WEATHER", "ARTIST_UNAVAILABLE")
    assert data["refund_tier"] in ("FULL_REFUND", "DEPOSIT_FORFEIT", "FULL_FORFEIT")
    assert isinstance(data["deposit_refund_cents"], int) and data["deposit_refund_cents"] >= 0
    assert isinstance(data["balance_relief_cents"], int) and data["balance_relief_cents"] >= 0


def assert_payment(data: dict):
    """Payment is immutable: only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "payment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["invoice_id"])
    assert data["applies_to"] in ("DEPOSIT", "BALANCE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["outcome"] == "SUCCEEDED"
