"""Entity assertions and domain invariant checkers.

Common-fields entities (Guest, Restaurant, ParkSession, DiningPlan, Reservation,
AllergyMeal, LightningLaneAddOn) carry id + created_at + updated_at + version
per PRD §2.4. NoShowFeeAssessment and CreditLedgerEntry are append-only — they
carry only id + created_at (PRD §2.4 second paragraph).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common helpers ───────────────────────────────────────────────────────

def _assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be int, got {type(data.get('version'))}"
    assert data["version"] >= 1


def _assert_append_only_fields(data: dict) -> None:
    """For NoShowFeeAssessment + CreditLedgerEntry: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ─── Entity assertions ────────────────────────────────────────────────────

def assert_guest(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_timezone"], str)
    assert isinstance(data["no_show_strike_count"], int)
    assert data["no_show_strike_count"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_restaurant(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["park_code"] in (
        "MAGIC_KINGDOM", "EPCOT", "ANIMAL_KINGDOM", "HOLLYWOOD_STUDIOS",
    )
    assert isinstance(data["capacity_per_slot"], int)
    assert 1 <= data["capacity_per_slot"] <= 400
    assert data["slot_minutes"] == 30
    assert isinstance(data["is_character_dining"], bool)
    assert isinstance(data["dining_plan_credit_cost"], int)
    assert 1 <= data["dining_plan_credit_cost"] <= 3
    assert isinstance(data["no_show_base_fee_cents"], int)
    assert data["no_show_base_fee_cents"] >= 0
    assert isinstance(data["opening_local_time"], str)
    assert isinstance(data["closing_local_time"], str)


def assert_park_session(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["guest_id"])
    assert data["park_code"] in (
        "MAGIC_KINGDOM", "EPCOT", "ANIMAL_KINGDOM", "HOLLYWOOD_STUDIOS",
    )
    assert isinstance(data["visit_date"], str) and len(data["visit_date"]) == 10
    assert data["status"] in ("NOT_STARTED", "ACTIVE", "CLOSED", "CANCELLED")


def assert_dining_plan(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["guest_id"])
    assert data["tier"] in ("STANDARD", "PLUS", "DELUXE")
    assert isinstance(data["table_service_credits_initial"], int)
    assert data["table_service_credits_initial"] >= 0
    assert isinstance(data["table_service_credits_remaining"], int)
    assert data["table_service_credits_remaining"] >= 0
    assert isinstance(data["table_service_credits_held"], int)
    assert data["table_service_credits_held"] >= 0
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_reservation(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["guest_id"])
    assert is_valid_uuid(data["restaurant_id"])
    assert is_valid_uuid(data["park_session_id"])
    assert is_valid_uuid(data["dining_plan_id"])
    assert is_iso8601_timestamp(data["slot_start_utc"])
    assert is_iso8601_timestamp(data["slot_end_utc"])
    assert isinstance(data["party_size"], int)
    assert 1 <= data["party_size"] <= 12
    assert isinstance(data["credits_debited"], int)
    assert data["credits_debited"] >= 0
    assert isinstance(data["credits_held"], int)
    assert data["credits_held"] >= 0
    assert data["status"] in (
        "PENDING", "CONFIRMED", "CHECKED_IN", "SEATED", "COMPLETED", "CANCELLED", "NO_SHOW",
    )


def assert_allergy_meal(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert isinstance(data["allergen_codes"], list)
    for code in data["allergen_codes"]:
        assert code in (
            "PEANUT", "TREE_NUT", "GLUTEN", "DAIRY", "EGG", "SHELLFISH", "SOY",
        )
    assert data["status"] in (
        "REQUESTED", "ACKNOWLEDGED", "PREPARED", "SERVED", "DECLINED",
    )


def assert_lightning_lane(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert data["tier"] in ("SINGLE_PASS", "MULTI_PASS")
    assert isinstance(data["fee_cents"], int)
    assert data["fee_cents"] >= 0
    assert data["status"] in (
        "REQUESTED", "ALLOCATED", "REDEEMED", "EXPIRED", "CANCELLED",
    )


def assert_no_show_fee_assessment(data: dict) -> None:
    """Append-only: id + created_at only; no updated_at, no version (PRD §2.4)."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["guest_id"])
    assert isinstance(data["base_amount_cents"], int)
    assert data["base_amount_cents"] >= 0
    assert isinstance(data["character_surcharge_cents"], int)
    assert data["character_surcharge_cents"] >= 0
    assert isinstance(data["repeat_offender_multiplier"], (int, float))
    assert isinstance(data["total_amount_cents"], int)
    assert data["total_amount_cents"] >= 0
    assert is_iso8601_timestamp(data["assessed_at"])


def assert_credit_ledger_entry(data: dict) -> None:
    """Append-only: id + created_at only; no updated_at, no version (PRD §2.4)."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["dining_plan_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert data["entry_type"] in ("HOLD", "RELEASE", "DEBIT", "REFUND")
    assert isinstance(data["credits_delta"], int)
    assert is_iso8601_timestamp(data["posted_at"])
