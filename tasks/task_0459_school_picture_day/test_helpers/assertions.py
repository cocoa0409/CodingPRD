"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Every entity carries id/created_at/updated_at/version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["school_name"], str) and len(data["school_name"]) > 0
    assert data["status"] in [
        "DRAFT", "ROSTER_LOCKED", "CAPTURE_OPEN", "GALLERY_OPEN",
        "ORDERING_CLOSED", "SETTLED", "CANCELLED",
    ]
    assert isinstance(data["retouch_budget_cents"], int)
    assert isinstance(data["retouch_credit_balance_cents"], int)
    assert isinstance(data["school_commission_balance_cents"], int)
    assert isinstance(data["total_merchandise_cents"], int)


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ["ENROLLED", "PHOTOGRAPHED", "ABSENT"]


def assert_photo(data: dict):
    _assert_common(data)
    assert data["status"] in ["UNMATCHED", "MATCHED", "RETAKE_REQUESTED", "RETAKEN", "APPROVED"]
    assert isinstance(data["match_confidence_score"], int)
    assert 0 <= data["match_confidence_score"] <= 100
    assert isinstance(data["yearbook_exported"], bool)


def assert_package(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["tier"] in ["BASIC", "DELUXE", "PREMIUM"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["active"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["CART", "SUBMITTED", "PAID", "FULFILLED", "REJECTED", "CANCELLED"]
    for field in ("subtotal_cents", "discount_cents", "merchandise_cents",
                  "shipping_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert isinstance(data["has_premium_line"], bool)


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_retouch_order(data: dict):
    _assert_common(data)
    assert data["kind"] in ["RETOUCH", "RETAKE"]
    assert data["status"] in ["REQUESTED", "APPROVED", "DONE", "REJECTED", "CANCELLED"]
    assert isinstance(data["gross_cost_cents"], int)
    assert isinstance(data["comp_discount_cents"], int)
    assert isinstance(data["net_cost_cents"], int)


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["distribution_method"] in ["SCHOOL_PICKUP", "HOME_DELIVERY"]
    assert data["status"] in ["PENDING", "DISPATCHED", "DELIVERED", "VOIDED"]


def assert_backdrop(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["active"], bool)


def assert_photographer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_capture_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["end_minute"] > data["start_minute"]


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #
def assert_retouch_credit_invariant(session: dict):
    """retouch_credit_balance_cents never exceeds the budget and never goes negative
    (PRD §3.5 — the balance is the budget minus reserved/finalized net costs)."""
    assert session["retouch_credit_balance_cents"] >= 0, "retouch credit cannot be negative"
    assert session["retouch_credit_balance_cents"] <= session["retouch_budget_cents"], \
        "retouch credit cannot exceed the budget"
