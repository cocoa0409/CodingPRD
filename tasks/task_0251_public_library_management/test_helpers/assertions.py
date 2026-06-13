"""Entity assertions and domain invariant checkers (PRD §2.4, §3.x).

Each assert_{entity} validates the response shape and field domains against the
PRD contract. Domain invariant checkers verify cross-field consistency rules.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every (mutable) entity: id, created_at,
    updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version is a positive int"


def assert_branch(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fine_free"], bool)
    for k in ("daily_fine_cents", "max_fine_cents", "grace_days", "loan_period_days",
              "block_threshold_cents", "reservation_buffer_minutes"):
        assert isinstance(data[k], int), f"{k} must be an integer"


def assert_patron(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["patron_type"] in ("ADULT", "JUVENILE", "STAFF")
    assert data["card_status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert data["borrowing_status"] in ("CLEAR", "BLOCKED")
    for k in ("checkout_limit", "hold_limit", "active_loan_count", "active_hold_count",
              "total_owed_cents", "ready_pickup_count"):
        assert isinstance(data[k], int), f"{k} must be an integer"
    assert data["total_owed_cents"] >= 0


def assert_title(data: dict):
    _assert_common(data)
    assert isinstance(data["isbn"], str)
    assert isinstance(data["title_text"], str) and len(data["title_text"]) > 0
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    for k in ("default_replacement_cents", "available_copy_count", "total_copy_count",
              "waiting_hold_count"):
        assert isinstance(data[k], int), f"{k} must be an integer"


def assert_copy(data: dict):
    _assert_common(data)
    assert isinstance(data["barcode"], str)
    assert data["status"] in ("AVAILABLE", "ON_LOAN", "ON_HOLD_SHELF", "LOST", "WITHDRAWN")
    assert isinstance(data["condition_factor"], (int, float))


def assert_loan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "OVERDUE", "RETURNED", "LOST")
    assert is_iso8601_timestamp(data["checked_out_at"])
    assert is_iso8601_timestamp(data["due_date"])
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    assert isinstance(data["accrued_fine_cents"], int) and data["accrued_fine_cents"] >= 0


def assert_hold(data: dict):
    _assert_common(data)
    assert data["status"] in ("WAITING", "READY", "FULFILLED", "CANCELLED", "EXPIRED")
    assert isinstance(data["queue_position"], int) and data["queue_position"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "CHECKED_IN", "COMPLETED",
                              "NO_SHOW", "CANCELLED")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_resource(data: dict):
    _assert_common(data)
    assert data["resource_kind"] in ("ROOM", "COMPUTER")
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")
    assert isinstance(data["capacity"], int)


def assert_ill_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "SHIPPED", "RECEIVED",
                              "RETURNED", "DENIED")
    assert isinstance(data["lending_fee_cents"], int)


def assert_license_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["total_licenses"], int)
    assert isinstance(data["loaned_licenses"], int)
    assert isinstance(data["available_licenses"], int)
    assert data["available_licenses"] >= 0, "available_licenses is never negative"


def assert_ebook_loan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RETURNED", "EXPIRED")
    assert is_iso8601_timestamp(data["checked_out_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_fine(data: dict):
    _assert_common(data)
    assert data["fine_type"] in ("OVERDUE", "LOST", "ILL_FEE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["settlement_status"] in ("UNPAID", "PAID", "WAIVED")


# --- Domain invariant checkers ---
def assert_pool_token_invariant(pool: dict):
    """loaned_licenses + available_licenses == total_licenses, available never
    negative (PRD §3.9)."""
    assert pool["available_licenses"] >= 0
    assert pool["loaned_licenses"] + pool["available_licenses"] == pool["total_licenses"], (
        f"token conservation: loaned {pool['loaned_licenses']} + available "
        f"{pool['available_licenses']} != total {pool['total_licenses']}"
    )
