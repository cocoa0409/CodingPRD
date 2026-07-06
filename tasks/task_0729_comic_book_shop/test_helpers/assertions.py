"""Entity assertions and domain invariant checkers.

Uses the framework's generic format validators (is_valid_uuid,
is_iso8601_timestamp) internally. Assertions cover only fields the PRD says the
implementer returns.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version — full common-field set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["store_credit_cents"], int)
    assert isinstance(data["lifetime_spend_cents"], int)
    assert data["status"] in ("ACTIVE", "BANNED")


def assert_comic_series(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["publisher"], str)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_comic_issue(data: dict):
    _assert_common(data)
    assert isinstance(data["series_id"], str)
    assert isinstance(data["issue_number"], str)
    assert isinstance(data["cover_price_cents"], int)
    assert isinstance(data["copies_ordered"], int)
    assert isinstance(data["copies_reserved"], int)
    assert isinstance(data["copies_allocated"], int)
    assert isinstance(data["copies_available"], int)
    assert data["status"] in ("SOLICITED", "ORDERED", "ON_SALE", "CLOSED")
    assert_issue_copy_invariant(data)


def assert_issue_copy_invariant(data: dict):
    """§2.7: copies_available + copies_allocated == copies_ordered, at all times;
    neither counter may fall below zero."""
    assert data["copies_available"] + data["copies_allocated"] == data["copies_ordered"], (
        "copies_available + copies_allocated must equal copies_ordered"
    )
    assert data["copies_available"] >= 0, "copies_available must not be negative"
    assert data["copies_allocated"] >= 0, "copies_allocated must not be negative"


def assert_pull_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["series_id"], str)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["issue_id"], str)
    assert isinstance(data["requested_qty"], int)
    assert isinstance(data["allocated_qty"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert data["status"] in (
        "RESERVED", "WAITLISTED", "ALLOCATED", "PULLED", "SOLD", "RELEASED", "EXPIRED",
    )


def assert_pre_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["issue_id"], str)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["estimated_total_cents"], int)
    assert data["status"] in ("PENDING", "CONFIRMED", "FULFILLED", "CANCELLED")


def assert_back_issue(data: dict):
    _assert_common(data)
    assert isinstance(data["series_id"], str)
    assert isinstance(data["issue_number"], str)
    assert data["condition"] in ("RAW", "GRADED")
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ("IN_STOCK", "RESERVED", "SOLD")


def assert_grading_submission(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["dispute_count"], int)
    assert data["status"] in (
        "INTAKE", "SUBMITTED", "AT_GRADER", "RETURNED", "READY_FOR_PICKUP", "PICKED_UP",
    )


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["store_location"], str)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["registered_count"], int)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "COMPLETED", "CANCELLED")


def assert_event_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["event_id"], str)
    assert data["status"] in ("REGISTERED", "CHECKED_IN", "CANCELLED", "NO_SHOW")


def assert_consignment(data: dict):
    _assert_common(data)
    assert isinstance(data["consignor_id"], str)
    assert isinstance(data["asking_price_cents"], int)
    assert data["status"] in (
        "RECEIVED", "LISTED", "SOLD", "RETURNED_TO_CONSIGNOR", "PAID_OUT",
    )


def assert_credit_transaction(data: dict):
    """Append-only ledger event: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in ("CONSIGNMENT_PAYOUT", "REFUND", "ADJUSTMENT", "REDEMPTION")
    assert isinstance(data["balance_after_cents"], int)
