"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ORDER_STATES = ["DRAFT", "CONFIRMED", "IN_FITTING", "REMAKE", "READY", "PICKED_UP", "CANCELLED"]
PROFILE_STATES = ["DRAFT", "LOCKED", "SUPERSEDED"]
FABRIC_STATES = ["AVAILABLE", "DISCONTINUED"]
RISK_BANDS = ["STANDARD", "WATCH", "HIGH_RISK"]
GROUP_STATES = ["FORMING", "LOCKED", "FULFILLED", "CANCELLED"]
FITTING_OUTCOMES = ["SCHEDULED", "PASSED", "FAILED"]
MILESTONES = ["BASTED", "FORWARD", "FINAL"]
PAYMENT_KINDS = ["DEPOSIT", "BALANCE"]
PAYMENT_STATES = ["CAPTURED", "REFUNDED"]
ALTERATION_STATES = ["OPEN", "COMPLETED", "VOIDED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0
    assert isinstance(data["remake_count"], int) and data["remake_count"] >= 0
    assert isinstance(data["completed_order_count"], int) and data["completed_order_count"] >= 0
    assert data["remake_risk_band"] in RISK_BANDS


def assert_measurement_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    for f in ("chest_cm", "waist_cm", "hip_cm", "inseam_cm"):
        assert isinstance(data[f], (int, float)) and data[f] > 0, f"{f} must be > 0"
    assert data["source"] in ["MANUAL", "BODY_SCAN"]
    assert data["status"] in PROFILE_STATES


def assert_fabric(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["price_per_meter_cents"], int) and data["price_per_meter_cents"] > 0
    assert isinstance(data["bolt_meters_remaining"], (int, float)) and data["bolt_meters_remaining"] >= 0
    assert data["status"] in FABRIC_STATES


def assert_tailor(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["skill_tier"] in ["APPRENTICE", "JOURNEYMAN", "MASTER"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_fitting_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_name"], str) and len(data["room_name"]) > 0
    assert isinstance(data["cleanup_buffer_minutes"], int) and data["cleanup_buffer_minutes"] >= 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["measurement_profile_id"])
    assert data["garment_type"] in ["SUIT", "JACKET", "TROUSERS", "SHIRT", "DRESS"]
    assert isinstance(data["base_labor_cents"], int) and data["base_labor_cents"] > 0
    assert isinstance(data["is_rush"], bool)
    assert isinstance(data["fabric_meters_required"], (int, float)) and data["fabric_meters_required"] > 0
    for f in ("quoted_total_cents", "locked_total_cents", "deposit_due_cents",
              "amount_paid_cents", "balance_due_cents", "store_credit_applied_cents",
              "remake_round"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative int"
    assert data["status"] in ORDER_STATES


def assert_option_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["fabric_id"])
    assert data["option_code"] in ["MONOGRAM", "CONTRAST_LINING", "WORKING_CUFFS", "PICK_STITCH", "EXTRA_TROUSER"]
    assert isinstance(data["upcharge_cents"], int) and data["upcharge_cents"] >= 0
    assert isinstance(data["fabric_price_per_meter_cents"], int) and data["fabric_price_per_meter_cents"] > 0


def assert_fitting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["tailor_id"])
    assert is_valid_uuid(data["room_id"])
    assert data["milestone"] in MILESTONES
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["outcome"] in FITTING_OUTCOMES


def assert_alteration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["description"], str)
    assert isinstance(data["billable_cents"], int) and data["billable_cents"] >= 0
    assert data["status"] in ALTERATION_STATES


def assert_payment(data: dict):
    # Payment is an append-only ledger entry: ONLY id + created_at among the
    # common fields. It MUST NOT carry updated_at or version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "payment id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "payment created_at must be ISO 8601"
    assert is_valid_uuid(data["order_id"])
    assert data["kind"] in PAYMENT_KINDS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in PAYMENT_STATES


def assert_group_order(data: dict):
    _assert_common(data)
    assert isinstance(data["event_name"], str) and len(data["event_name"]) > 0
    assert isinstance(data["member_order_count"], int) and data["member_order_count"] >= 0
    assert isinstance(data["group_total_cents"], int) and data["group_total_cents"] >= 0
    assert data["status"] in GROUP_STATES


def assert_pickup(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["released_to_name"], str) and len(data["released_to_name"]) > 0
    assert is_iso8601_timestamp(data["picked_up_at"])


# ─── Domain invariant checkers ──────────────────────────────────────────

def assert_order_balance_invariants(data: dict):
    """Balance never negative; amount paid + credit applied never exceeds locked total."""
    assert data["balance_due_cents"] >= 0, "balance_due_cents must never go negative"
    assert data["amount_paid_cents"] + data["store_credit_applied_cents"] <= data["locked_total_cents"], \
        "amount paid + credit applied must not exceed locked total"
