"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates structural shape (id/timestamps/types/enum
membership) of a resource returned by the API. Invariant checkers validate
relationships the PRD requires to hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_FULFILLMENT_STATES = ["PLACED", "PICKING", "STAGED", "HANDED_OFF", "CANCELLED"]
_PAYMENT_STATES = ["AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED"]
_LINE_STATES = ["PENDING", "PICKED", "SUBSTITUTED", "OUT_OF_STOCK", "CANCELLED"]
_SUB_STATES = ["PROPOSED", "ACCEPTED", "REJECTED"]
_SUB_POLICIES = ["NO_SUBSTITUTION", "SAME_PRICE_OR_LESS", "SHOPPER_CHOICE"]


def _assert_common(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1 and increments on each mutation"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ebt_enabled"], bool)
    assert isinstance(data["cold_chain_hold_minutes"], int)
    assert data["status"] in ["ACTIVE", "CLOSED"], f"unexpected store status {data['status']!r}"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["snap_ebt_balance_cents"], int)
    assert data["snap_ebt_balance_cents"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"], f"unexpected customer status {data['status']!r}"


def assert_picker(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["window_cooldown_minutes"], int)
    assert data["status"] in ["AVAILABLE", "OFF_SHIFT"], f"unexpected picker status {data['status']!r}"


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["sku"], str)
    assert data["pricing_mode"] in ["UNIT", "WEIGHT"], f"unexpected pricing_mode {data['pricing_mode']!r}"
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 0, "unit_price_cents must be >= 0"
    assert isinstance(data["ebt_eligible"], bool)
    assert isinstance(data["age_restricted"], bool)
    assert isinstance(data["cold_chain"], bool)
    assert data["status"] in ["ACTIVE", "DISCONTINUED"], f"unexpected product status {data['status']!r}"


def assert_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert data["slot_type"] in ["DELIVERY", "PICKUP"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert data["status"] in ["OPEN", "FULL", "CLOSED"], f"unexpected slot status {data['status']!r}"


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["slot_id"])
    assert data["fulfillment_status"] in _FULFILLMENT_STATES, (
        f"unexpected fulfillment_status {data['fulfillment_status']!r}"
    )
    assert data["payment_status"] in _PAYMENT_STATES, (
        f"unexpected payment_status {data['payment_status']!r}"
    )
    for f in (
        "tip_cents", "estimated_total_cents", "estimated_ebt_eligible_cents",
        "final_total_cents", "final_ebt_eligible_cents", "ebt_charged_cents",
        "card_charged_cents", "refunded_total_cents", "net_captured_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int, got {data.get(f)!r}"
    assert isinstance(data["requires_age_check"], bool)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["substitution_policy"] in _SUB_POLICIES
    assert isinstance(data["estimated_line_cents"], int)
    assert isinstance(data["final_line_cents"], int)
    assert data["status"] in _LINE_STATES, f"unexpected line status {data['status']!r}"


def assert_substitution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["substitute_product_id"])
    assert isinstance(data["substitute_line_cents"], int)
    assert data["status"] in _SUB_STATES, f"unexpected substitution status {data['status']!r}"


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["ebt_amount_cents"], int)
    assert isinstance(data["card_amount_cents"], int)
    assert isinstance(data["grand_total_cents"], int)
    assert data["status"] == "CAPTURED"


def assert_age_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["verifier_user_id"], str)
    assert data["outcome"] in ["PASS", "FAIL"], f"unexpected outcome {data['outcome']!r}"


def assert_refund(data: dict):
    """Refund is an append-only event record (common_fields:false): it exposes only
    id and created_at, never updated_at or version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "refund id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["order_line_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] == "OUT_OF_STOCK"


def assert_refund_has_no_version_fields(data: dict):
    """PRD §2.4: a Refund has no updated_at and no version, because once written it
    is never modified."""
    assert "version" not in data, "Refund must not expose a version field"
    assert "updated_at" not in data, "Refund must not expose an updated_at field"


# ─── Domain invariant checkers ────────────────────────

def assert_split_tender_invariants(order: dict):
    """PRD §3.6: the two buckets always sum to final_total_cents, the EBT bucket
    never exceeds the benefit balance, and the EBT bucket never exceeds the
    eligible portion."""
    assert order["ebt_charged_cents"] + order["card_charged_cents"] == order["final_total_cents"], (
        "ebt_charged_cents + card_charged_cents must equal final_total_cents"
    )
    assert order["ebt_charged_cents"] <= order["final_ebt_eligible_cents"], (
        "ebt_charged_cents must not exceed final_ebt_eligible_cents"
    )


def assert_net_captured_identity(order: dict):
    """PRD §3.8: net_captured_cents == ebt_charged_cents + card_charged_cents -
    refunded_total_cents."""
    assert (
        order["net_captured_cents"]
        == order["ebt_charged_cents"] + order["card_charged_cents"] - order["refunded_total_cents"]
    ), "net_captured_cents must equal captured total minus refunded_total_cents"
