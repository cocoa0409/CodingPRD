"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}
_TEMPLATE_CATEGORIES = {"HOLIDAY", "CORPORATE_WELCOME", "CLIENT_APPRECIATION", "CUSTOM"}
_CARD_STOCKS = {"MATTE", "GLOSS", "RECYCLED"}
_OCCASIONS = {"HOLIDAY", "ANNIVERSARY", "ONBOARDING", "THANK_YOU", "CUSTOM"}
_APPROVAL_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED"}
_PRODUCTION_STATUSES = {"DRAFT", "ASSEMBLING", "READY_TO_SHIP", "SHIPPED",
                        "COMPLETED", "CANCELLED"}
_IMPORT_ROW_STATUSES = {"ACCEPTED", "REJECTED"}
_PROOF_STATUSES = {"DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "LOCKED"}
_RESERVATION_STATUSES = {"RESERVED", "ALLOCATED", "ASSEMBLED", "RELEASED",
                         "EXPIRED", "CANCELLED"}
_TASK_STATUSES = {"QUEUED", "IN_PROGRESS", "COMPLETE", "FAILED"}
_SHIPMENT_STATUSES = {"CREATED", "LABEL_GENERATED", "IN_TRANSIT", "DELIVERED",
                      "EXCEPTION", "RETURNED"}
_DECISION_VALUES = {"PENDING", "APPROVED", "REJECTED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["billing_email"], str) and "@" in data["billing_email"]
    assert isinstance(data["monthly_budget_cents"], int)
    assert data["monthly_budget_cents"] > 0
    assert isinstance(data["approval_threshold_cents"], int)
    assert data["approval_threshold_cents"] >= 0
    assert isinstance(data["ytd_spend_cents"], int)
    assert data["ytd_spend_cents"] >= 0
    assert data["status"] in _ACCOUNT_STATUSES
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_template(data: dict):
    _assert_common(data)
    assert data["category"] in _TEMPLATE_CATEGORIES
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["is_perishable"], bool)
    assert isinstance(data["active"], bool)
    assert isinstance(data["components"], list)


def assert_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["is_perishable"], bool)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0


def assert_branding_profile(data: dict):
    _assert_common(data)
    assert data["card_stock"] in _CARD_STOCKS
    assert isinstance(data["approved"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert data["occasion"] in _OCCASIONS
    assert data["approval_status"] in _APPROVAL_STATUSES
    assert data["production_status"] in _PRODUCTION_STATUSES
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cost_cents"], int)
    assert isinstance(data["requires_approval"], bool)


def assert_recipient(data: dict):
    _assert_common(data)
    assert data["import_row_status"] in _IMPORT_ROW_STATUSES
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_message_proof(data: dict):
    _assert_common(data)
    assert data["proof_status"] in _PROOF_STATUSES
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_inventory_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in _RESERVATION_STATUSES
    assert isinstance(data["reserved_qty"], int)


def assert_assembly_station(data: dict):
    _assert_common(data)
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] > 0
    # Config-only: no updated_at / no version
    assert "updated_at" not in data, "AssemblyStation is config-only (no updated_at)"
    assert "version" not in data, "AssemblyStation is config-only (no version)"


def assert_assembly_task(data: dict):
    _assert_common(data)
    assert data["status"] in _TASK_STATUSES


def assert_shipping_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["country_codes"], list)
    # Config-only: no updated_at / no version
    assert "updated_at" not in data, "ShippingZone is config-only (no updated_at)"
    assert "version" not in data, "ShippingZone is config-only (no version)"


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in _SHIPMENT_STATUSES
    assert isinstance(data["shipping_cost_cents"], int)


def assert_budget_approval(data: dict):
    _assert_common(data)
    assert data["decision"] in _DECISION_VALUES


def assert_recurring_series(data: dict):
    _assert_common(data)
    assert isinstance(data["active"], bool)
    assert isinstance(data["interval_days"], int) and data["interval_days"] > 0
