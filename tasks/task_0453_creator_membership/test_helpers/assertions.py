"""Entity assertions and domain invariant checkers for the Creator Membership API.

Each assert_{entity}(data) validates the shape of a returned resource against
the PRD's field contract. Entities with the four common fields carry id,
created_at, updated_at, version; the two immutable record types (PostAccess,
Message) carry only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """id (UUID) + created_at/updated_at (ISO 8601) + version (int) — for the
    nine resources that carry all four common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_immutable_record_fields(data: dict):
    """id (UUID) + created_at only — PostAccess and Message carry NO version or
    updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable record must NOT carry a version field"
    assert "updated_at" not in data, "immutable record must NOT carry an updated_at field"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_creator(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["platform_plan"] in ("STARTER", "PRO", "PREMIUM")
    assert data["billing_mode"] in ("MONTHLY", "PER_CREATION")
    assert data["charge_timing"] in ("UP_FRONT", "END_OF_MONTH")
    assert isinstance(data["pending_payout_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_tier(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["creator_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["billing_model"] in ("MONTHLY", "PER_CREATION")
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert isinstance(data["active_pledge_count"], int)


def assert_patron(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents must never be negative"
    assert data["status"] == "ACTIVE"


def assert_pledge(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["patron_id"])
    assert is_valid_uuid(data["creator_id"])
    assert is_valid_uuid(data["tier_id"])
    assert data["billing_model"] in ("MONTHLY", "PER_CREATION")
    assert data["lifecycle_status"] in ("DRAFT", "ACTIVE", "PAUSED", "CANCELLED")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "GRACE", "LAPSED")
    assert isinstance(data["current_cycle_charged_cents"], int)


def assert_charge(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["pledge_id"])
    assert is_valid_uuid(data["creator_id"])
    assert data["charge_kind"] in (
        "INITIAL_PRORATION", "CYCLE_RENEWAL", "UPGRADE_PRORATION", "PER_CREATION", "WIN_BACK",
    )
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["wallet_applied_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["status"] in ("PENDING", "SUCCEEDED", "FAILED", "REFUNDED")
    # net = gross - wallet_applied (PRD §3.5)
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["wallet_applied_cents"], (
        "net_amount_cents must equal gross_amount_cents - wallet_applied_cents"
    )


def assert_post(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["creator_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["min_tier_rank"], int) and data["min_tier_rank"] >= 0
    assert isinstance(data["is_paid_creation"], bool)
    assert data["status"] in ("DRAFT", "PUBLISHED")


def assert_post_access(data: dict):
    assert_immutable_record_fields(data)
    assert is_valid_uuid(data["post_id"])
    assert is_valid_uuid(data["patron_id"])
    assert isinstance(data["granted_tier_rank"], int)


def assert_conversation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["creator_id"])
    assert is_valid_uuid(data["patron_id"])
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["message_count"], int)


def assert_message(data: dict):
    assert_immutable_record_fields(data)
    assert is_valid_uuid(data["conversation_id"])
    assert data["sender_role"] in ("CREATOR", "PATRON")
    assert isinstance(data["body"], str)


def assert_payout(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["creator_id"])
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["platform_fee_cents"], int)
    assert isinstance(data["processing_fee_cents"], int)
    assert isinstance(data["payout_amount_cents"], int)
    assert isinstance(data["swept_charge_count"], int)
    assert data["status"] in ("PENDING", "PAID", "REVERSED")
    # payout_amount = gross - platform_fee - processing_fee (PRD §3.7)
    assert data["payout_amount_cents"] == (
        data["gross_cents"] - data["platform_fee_cents"] - data["processing_fee_cents"]
    ), "payout_amount_cents must equal gross_cents - platform_fee_cents - processing_fee_cents"


def assert_win_back_offer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["pledge_id"])
    assert isinstance(data["discount_pct"], (int, float))
    assert 0 < data["discount_pct"] < 1
    assert data["status"] in ("OFFERED", "REDEEMED", "EXPIRED")
