"""Entity assertions and domain invariant checkers.

Field names are exactly as the PRD describes them. Append-only ledger entries
are asserted without updated_at/version, per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id (UUID), created_at + updated_at (ISO8601), version (int >= 1) — PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at its initial value and is >= 1"


def assert_pricing_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    for f in (
        "wash_base_cents", "dry_base_cents_per_block", "dry_block_minutes",
        "surge_multiplier_bps", "surge_start_hour_utc", "surge_end_hour_utc",
        "wdf_rate_cents_per_lb", "wdf_minimum_cents",
        "reload_bonus_tier1_min_cents", "reload_bonus_tier1_bps",
        "reload_bonus_tier2_min_cents", "reload_bonus_tier2_bps",
        "loyalty_cents_per_point", "loyalty_redeem_threshold_points",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer count"


def assert_machine(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str)
    assert data["machine_type"] in ("WASHER", "DRYER")
    assert isinstance(data["capacity_lb"], int) and data["capacity_lb"] > 0
    assert data["status"] in ("IDLE", "RUNNING", "DONE", "FAULT", "OUT_OF_SERVICE")
    assert isinstance(data["lifetime_vend_count"], int) and data["lifetime_vend_count"] >= 0
    assert isinstance(data["fault_count"], int) and data["fault_count"] >= 0


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["phone"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    # Wallet, points, credits, lifetime spend are never negative (PRD §2.6).
    for f in ("wallet_cents", "loyalty_points", "free_wash_credits", "lifetime_spend_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
        assert data[f] >= 0, f"{f} is never negative"


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["attendant_id"], str)
    assert data["status"] in ("OPEN", "RECONCILING", "CLOSED")
    assert isinstance(data["opening_float_cents"], int) and data["opening_float_cents"] >= 0
    for f in ("coin_collected_cents", "cash_reload_cents", "cash_refund_paid_cents",
              "expected_drawer_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_vend(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["machine_id"]), "machine_id must be a UUID"
    assert data["payment_method"] in ("COIN", "CARD", "APP_WALLET")
    assert data["payment_status"] in ("CAPTURED", "REFUNDED")
    assert data["cycle_status"] in ("RUNNING", "COMPLETED", "ABORTED")
    for f in ("quoted_amount_cents", "charged_amount_cents", "loyalty_points_earned"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["surge_applied"], bool)


def assert_reload(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"]), "member_id must be a UUID"
    assert data["tender"] in ("CASH", "CARD", "APP")
    assert data["status"] == "POSTED"
    for f in ("principal_cents", "bonus_cents", "credited_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_wdf_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["intake_attendant_id"], str)
    assert isinstance(data["weight_lb"], int) and data["weight_lb"] > 0
    assert data["status"] in ("DROPPED", "WASHING", "READY", "PAID", "CANCELLED")
    assert isinstance(data["quoted_total_cents"], int)


def assert_refund_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vend_id"]), "vend_id must be a UUID"
    assert data["reason"] in ("MACHINE_FAULT", "NO_CYCLE", "DOUBLE_CHARGE")
    assert data["refund_destination"] in ("WALLET", "CASH", "ORIGINAL_TENDER")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")
    for f in ("requested_cents", "approved_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_lost_found_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["logged_by_id"], str)
    assert isinstance(data["description"], str)
    assert data["status"] in ("LOGGED", "CLAIMED", "DISPOSED")
    assert is_iso8601_timestamp(data.get("found_at", "")), "found_at must be ISO 8601"


def assert_loyalty_ledger_entry(data: dict):
    """Append-only audit record: id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "loyalty ledger entry has no updated_at (PRD §2.4)"
    assert "version" not in data, "loyalty ledger entry has no version (PRD §2.4)"
    assert data["entry_type"] in ("ACCRUAL", "REVERSAL", "REDEMPTION")
    assert isinstance(data["points_delta"], int)
    assert isinstance(data["balance_after"], int)
