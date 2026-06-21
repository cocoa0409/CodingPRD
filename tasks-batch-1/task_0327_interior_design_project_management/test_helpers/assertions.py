"""Entity assertions and domain invariant checkers (Interior Design PM API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PROJECT_STATUSES = ["BRIEFING", "IN_DESIGN", "PROCUREMENT", "INSTALLATION", "CLOSED", "ON_HOLD"]
_POSTURES = ["OPEN", "BUDGET_REVIEW", "FROZEN"]
_BUDGET_STATUSES = ["GREEN", "AMBER", "RED"]
_FEE_MODELS = ["FLAT", "HOURLY", "MARKUP"]
_ROOM_STATUSES = ["SCOPING", "MOODBOARD_READY", "APPROVED", "REWORK"]
_MOODBOARD_STATUSES = ["DRAFT", "PRESENTED", "ACCEPTED", "SUPERSEDED"]
_FFE_CATEGORIES = ["FURNITURE", "LIGHTING", "TEXTILE", "DECOR", "FIXTURE"]
_SELECTION_STATUSES = ["PROPOSED", "SPECIFIED", "ORDERED", "WITHDRAWN"]
_VENDOR_TRADES = ["SUPPLIER", "UPHOLSTERY", "MILLWORK", "ELECTRICAL", "GENERAL"]
_VENDOR_STANDINGS = ["ACTIVE", "SUSPENDED"]
_ORDER_STATUSES = ["DRAFT", "ORDERED", "IN_TRANSIT", "DELIVERED", "CLOSED", "CANCELLED", "RETURNED"]
_REVISION_KINDS = ["ROOM", "SELECTION"]
_REVISION_STATUSES = ["DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "RESOLVED", "DISMISSED"]
_PUNCH_SEVERITIES = ["MINOR", "MAJOR", "BLOCKING"]
_PUNCH_STATUSES = ["OPEN", "RESOLVED", "WAIVED"]
_TIME_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED"]


def _assert_common(data: dict):
    """id/created_at/updated_at/version present and well-formed (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["client_name"], str)
    assert isinstance(data["client_user_id"], str)
    assert isinstance(data["budget_cents"], int)
    assert data["fee_model"] in _FEE_MODELS, f"unexpected fee_model {data.get('fee_model')!r}"
    assert data["status"] in _PROJECT_STATUSES, f"unexpected status {data.get('status')!r}"
    assert data["posture"] in _POSTURES, f"unexpected posture {data.get('posture')!r}"
    assert data["budget_status"] in _BUDGET_STATUSES
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["design_fee_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)
    assert isinstance(data["client_credit_cents"], int)


def assert_project_ledger_invariants(data: dict):
    """Ledger relationships that must always hold (PRD §2.8, §3.6, §3.8)."""
    assert data["committed_cents"] >= 0, "committed_cents must be non-negative"
    assert data["design_fee_cents"] >= 0, "design_fee_cents must be non-negative"
    assert data["client_credit_cents"] >= 0, "client_credit_cents must be non-negative"
    # budget_remaining = budget - committed - design_fee (PRD §3.8).
    expected_remaining = data["budget_cents"] - data["committed_cents"] - data["design_fee_cents"]
    assert data["budget_remaining_cents"] == expected_remaining, (
        f"budget_remaining_cents {data['budget_remaining_cents']} != "
        f"budget - committed - fee ({expected_remaining})"
    )


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["email"], str)


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["name"], str)
    assert data["status"] in _ROOM_STATUSES, f"unexpected room status {data.get('status')!r}"
    # approved_moodboard_id is null until APPROVED.
    assert "approved_moodboard_id" in data


def assert_moodboard(data: dict):
    _assert_common(data)
    assert isinstance(data["room_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["palette"], list)
    assert data["status"] in _MOODBOARD_STATUSES


def assert_ffe_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert data["category"] in _FFE_CATEGORIES
    assert isinstance(data["list_unit_cost_cents"], int) and data["list_unit_cost_cents"] > 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["active"], bool)


def assert_selection(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["room_id"], str)
    assert isinstance(data["ffe_item_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["line_net_cents"], int)
    assert data["status"] in _SELECTION_STATUSES


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["trade"] in _VENDOR_TRADES
    assert data["standing"] in _VENDOR_STANDINGS
    assert isinstance(data["lead_time_buffer_days"], int) and data["lead_time_buffer_days"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert data["status"] in _ORDER_STATUSES
    assert isinstance(data["order_subtotal_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_order_line(data: dict):
    """OrderLine is an append-only join row: ONLY id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["order_id"], str)
    assert isinstance(data["selection_id"], str)
    assert isinstance(data["line_net_cents_snapshot"], int)


def assert_revision(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["target_kind"] in _REVISION_KINDS
    assert isinstance(data["target_id"], str)
    assert isinstance(data["round_no"], int) and data["round_no"] >= 1
    assert data["status"] in _REVISION_STATUSES


def assert_punch_item(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["description"], str)
    assert data["severity"] in _PUNCH_SEVERITIES
    assert data["status"] in _PUNCH_STATUSES


def assert_time_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["minutes"], int) and data["minutes"] >= 1
    assert isinstance(data["billable"], bool)
    assert data["status"] in _TIME_STATUSES


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
