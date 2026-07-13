"""Entity assertions and domain invariant checkers.

Validate response structure against the PRD contract. Uses the framework's generic
format checkers internally. Photo carries only id + created_at (no updated_at/version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents must be non-negative"


def assert_address(data: dict):
    _assert_common(data)
    assert isinstance(data["recipient_name"], str)
    assert isinstance(data["is_default"], bool)


def assert_template(data: dict):
    _assert_common(data)
    assert data["product_type"] in ("PHOTOBOOK", "CARD", "CANVAS", "CALENDAR")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["allowed_finishes"], list) and len(data["allowed_finishes"]) >= 1


def assert_project(data: dict):
    _assert_common(data)
    assert data["state"] in ("DRAFT", "LAID_OUT", "IN_PROOF", "APPROVED")
    assert isinstance(data["photo_count"], int)
    assert isinstance(data["placed_photo_count"], int)


def assert_photo(data: dict):
    assert is_valid_uuid(data.get("id", "")), "photo id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("UPLOADED", "PLACED", "LOCKED")
    # Photo has no updated_at and no version (PRD 2.4).
    assert "version" not in data, "Photo must not carry a version field"
    assert "updated_at" not in data, "Photo must not carry an updated_at field"


def assert_proof(data: dict):
    _assert_common(data)
    assert data["state"] in ("GENERATED", "APPROVED", "CHANGES_REQUESTED", "SUPERSEDED")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("NEW", "IN_PRODUCTION", "SHIPPED", "DELIVERED", "CANCELLED")
    for f in ("unit_price_cents", "subtotal_cents", "discount_cents", "shipping_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"
    assert data["total_cents"] >= 0, "total_cents floored at 0"


def assert_production_job(data: dict):
    _assert_common(data)
    assert data["state"] in ("QUEUED", "PRINTING", "FINISHING", "DONE", "CANCELLED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["state"] in ("LABEL_CREATED", "IN_TRANSIT", "DELIVERED", "VOID")


def assert_promotion(data: dict):
    _assert_common(data)
    assert data["kind"] in ("PERCENT", "FLAT", "FREE_SHIP")


def assert_surge_window(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_per_day"], int) and data["capacity_per_day"] >= 1
