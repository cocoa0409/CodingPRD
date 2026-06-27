"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validate response structure against the PRD contract,
using the framework's generic format checkers internally. Invariant checkers
verify cross-field rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id/created_at/updated_at/version for entities carrying the full common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["lifetime_spend_cents"], int)
    assert isinstance(data["store_credit_balance_cents"], int)
    assert data["store_credit_balance_cents"] >= 0, "balance never negative"
    assert data["status"] in ("ACTIVE", "BANNED")


def assert_inventory_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["product_kind"] in ("SINGLE", "SEALED")
    assert data["condition"] in (
        "MINT", "NEAR_MINT", "LIGHTLY_PLAYED", "MODERATELY_PLAYED", "DAMAGED")
    assert isinstance(data["market_price_cents"], int)
    assert data["quantity_on_hand"] >= 0
    assert data["quantity_reserved"] >= 0
    assert data["quantity_reserved"] <= data["quantity_on_hand"], \
        "reserved never exceeds on-hand"


def assert_buylist_submission(data: dict):
    _assert_common_fields(data)
    assert data["payout_method"] in ("STORE_CREDIT", "CASH")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "VOIDED")
    assert isinstance(data["offered_total_cents"], int)


def assert_release_product(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PRE_ORDER_OPEN", "RELEASED")
    assert data["quantity_allocated"] >= 0
    assert data["quantity_allocated"] <= data["allocation_pool"], \
        "allocated never exceeds pool"


def assert_pre_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "ALLOCATED", "FULFILLED", "CANCELLED", "WAITLISTED")
    assert isinstance(data["priority_score"], int)
    assert data["requested_quantity"] >= 1


def assert_event(data: dict):
    _assert_common_fields(data)
    assert data["format"] in ("STANDARD", "MODERN", "COMMANDER", "DRAFT")
    assert data["status"] in (
        "SCHEDULED", "OPEN", "IN_PROGRESS", "COMPLETE", "CANCELLED")
    assert data["seated_count"] >= 0
    assert data["seated_count"] <= data["capacity"], "seated never exceeds capacity"
    assert data["current_round"] >= 0


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["checkin_status"] in ("PENDING", "CHECKED_IN", "WITHDRAWN")
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["charged_fee_cents"], int)
    assert isinstance(data["match_points"], int)


def assert_pairing(data: dict):
    _assert_common_fields(data)
    assert data["result"] in ("PENDING", "A_WINS", "B_WINS", "DRAW", "BYE_A")
    assert isinstance(data["round_number"], int)


def assert_grading_submission(data: dict):
    _assert_common_fields(data)
    assert data["service_tier"] in ("ECONOMY", "STANDARD", "EXPRESS")
    assert data["status"] in ("INTAKE", "AT_GRADER", "GRADED", "REJECTED", "RETURNED")
    assert isinstance(data["grading_fee_cents"], int)


def assert_consignment_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("LISTED", "SOLD", "WITHDRAWN", "SETTLED")
    assert isinstance(data["payout_total_cents"], int)
    assert 0 <= data["commission_rate_bps"] <= 10000


def assert_ledger_row(data: dict):
    """Append-only ledger: id + created_at ONLY; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "ledger id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reason"] in (
        "BUYLIST_PAYOUT", "EVENT_REFUND", "CONSIGNMENT_PAYOUT", "PREORDER_DEPOSIT",
        "EVENT_CHARGE", "PREORDER_FULFILL", "MANUAL_ADJUSTMENT")
    assert isinstance(data["delta_cents"], int)
