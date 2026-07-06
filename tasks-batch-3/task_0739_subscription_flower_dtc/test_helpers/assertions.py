"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --- Entity assertions ---


def _common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID; got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _append_only_fields(data: dict):
    """common_fields: false — id and created_at only; must NOT carry updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID; got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["lifetime_cycles"], int) and data["lifetime_cycles"] >= 0
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["wallet_credit_cents"], int)


def assert_plan(data: dict):
    _common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cadence"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert data.get("default_style") in ("ROUND", "GARDEN", "EUROPEAN")
    assert isinstance(data["is_active"], bool)


def assert_subscription(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["size"] in ("PETITE", "ORIGINAL", "DELUXE", "GRAND")
    assert data["style"] in ("ROUND", "GARDEN", "EUROPEAN")
    assert isinstance(data["vase_addon"], bool)
    assert isinstance(data["is_gift"], bool)
    assert data["lifecycle_status"] in ("ACTIVE", "PAUSED", "CANCELLED", "EXPIRED")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE")
    assert isinstance(data["current_cycle_index"], int) and data["current_cycle_index"] >= 1
    assert is_iso8601_timestamp(data["next_renewal_date"])
    assert isinstance(data["renewal_price_cents"], int)


def assert_shipment(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert is_iso8601_timestamp(data["scheduled_delivery_date"])
    assert data["status"] in (
        "SCHEDULED",
        "SKIPPED",
        "SOURCING",
        "SOURCED",
        "SUBSTITUTED",
        "SHIPPED",
        "DELIVERED",
        "CANCELLED",
    )
    assert isinstance(data["substitution_applied"], bool)


def assert_stem_lot(data: dict):
    _common_fields(data)
    assert isinstance(data["variety"], str)
    assert data["grade"] in ("A", "B", "C")
    assert isinstance(data["quantity_total"], int) and data["quantity_total"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert is_iso8601_timestamp(data["sourced_at"])
    assert isinstance(data["shelf_life_hours"], int) and data["shelf_life_hours"] > 0
    assert isinstance(data["quantity_available"], int) and data["quantity_available"] >= 0
    assert is_iso8601_timestamp(data["usable_until"])
    assert data["cold_chain_state"] in ("FRESH", "EXPIRED")


def assert_stem_allocation(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["shipment_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] > 0
    assert is_iso8601_timestamp(data["hold_start"])
    assert is_iso8601_timestamp(data["hold_end"])
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")


def assert_carrier_route(data: dict):
    _common_fields(data)
    assert isinstance(data["zone"], str)
    assert is_iso8601_timestamp(data["service_date"])


def assert_charge(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["kind"] in ("RENEWAL", "UPCHARGE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("PENDING", "CAPTURED", "FAILED", "REFUNDED")
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0


def assert_wallet_entry(data: dict):
    """WalletEntry is append-only: id + created_at only, no updated_at or version."""
    _append_only_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in ("REFUND", "SKIP_CREDIT", "ADJUSTMENT")


def assert_win_back_offer(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["discount_pct"], (int, float))
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("OFFERED", "REDEEMED", "EXPIRED")


def assert_substitution_rule(data: dict):
    """SubstitutionRule is append-only config: id + created_at only."""
    _append_only_fields(data)
    assert isinstance(data["from_variety"], str)
    assert isinstance(data["to_variety"], str)
    assert isinstance(data["allowed"], bool)


# --- Domain invariants (PRD §2.5) ---


def assert_stem_conservation(lot_before_total: int, lot_after_available: int, stems_active: int):
    """PRD §2.5: quantity_total == quantity_available + sum of active-allocation stems."""
    assert lot_before_total == lot_after_available + stems_active, (
        f"stem conservation violated: total {lot_before_total} != available "
        f"{lot_after_available} + active {stems_active}"
    )


def assert_wallet_conservation(wallet_credit_cents: int, wallet_entries: list):
    """PRD §2.5: wallet balance == sum(WalletEntry.amount_cents) for the customer."""
    total = sum(e["amount_cents"] for e in wallet_entries)
    assert wallet_credit_cents == total, (
        f"wallet conservation violated: wallet_credit_cents {wallet_credit_cents} "
        f"!= sum(entries) {total}"
    )
