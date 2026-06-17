"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies the common resource properties (UUID id, ISO 8601
created_at, and — for these full entities — updated_at and integer version) plus
the entity-specific fields and their enum domains. Invariant checkers verify the
conserved-ledger relationships the PRD guarantees.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and only increments"


def assert_shop(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["currency"], str)
    for f in ("tax_rate_bps", "deposit_pct_bps", "retainage_pct_bps",
              "rush_surcharge_bps", "max_installs_per_day", "change_order_buffer_pct_bps"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert "current_utc" in data, "shop must expose current_utc"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["lifetime_paid_cents"], int)


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["shop_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["is_rush"], bool)
    assert data["margin_policy"] in ("STANDARD", "PREMIUM")
    assert data["status"] in (
        "DRAFT", "MEASURED", "QUOTED", "CONTRACTED", "IN_PRODUCTION",
        "CHANGE_PENDING", "READY_FOR_DELIVERY", "INSTALLED", "CLOSED", "CANCELLED",
    )
    for f in ("estimate_total_cents", "contract_total_cents", "deposit_required_cents",
              "billed_to_date_cents", "paid_to_date_cents", "open_change_delta_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer cents value"


def assert_spec(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["label"], str)
    for f in ("width_mm", "height_mm", "depth_mm"):
        assert isinstance(data[f], int) and data[f] > 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["base_unit_price_cents"], int) and data["base_unit_price_cents"] >= 0
    assert isinstance(data["panel_area_mm2"], int)
    assert isinstance(data["material_id"], str)
    assert data["lock_state"] in ("OPEN", "LOCKED")


def assert_material(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["sheet_area_mm2"], int) and data["sheet_area_mm2"] > 0
    assert isinstance(data["sheet_price_cents"], int) and data["sheet_price_cents"] >= 0
    for f in ("on_hand_sheets", "reserved_sheets", "available_sheets"):
        assert isinstance(data[f], int), f"{f} must be a whole integer sheet count"


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["material_id"], str)
    assert isinstance(data["sheets"], int) and data["sheets"] >= 1
    assert data["status"] in ("HELD", "COMMITTED", "CONSUMED", "RELEASED")


def assert_machine(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["changeover_buffer_min"], int) and data["changeover_buffer_min"] >= 0
    assert data["status"] in ("ONLINE", "OFFLINE")


def assert_build_job(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["machine_id"], str)
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETE", "CANCELLED")


def assert_finish_selection(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["finish_code"] in ("RAW", "STAIN", "PAINT", "LACQUER")
    assert data["sheen"] in ("MATTE", "SATIN", "GLOSS")
    assert isinstance(data["is_active"], bool)


def assert_draw(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["draw_type"] in ("DEPOSIT", "PROGRESS", "RETAINAGE")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert data["status"] in ("PENDING", "ISSUED", "PAID", "VOIDED")


def assert_change_order(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["spec_price_delta_cents"], int)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "REVISING", "CANCELLED")


def assert_installation(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["install_date"], str)
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PUNCH_PENDING", "COMPLETE", "CANCELLED")


def assert_punch_item(data: dict):
    _assert_common(data)
    assert isinstance(data["installation_id"], str)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["description"], str)
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_material_ledger_conserved(data: dict):
    """available_sheets must equal on_hand_sheets - reserved_sheets, and every
    count is a non-negative whole integer (the conserved stock ledger)."""
    assert data["available_sheets"] == data["on_hand_sheets"] - data["reserved_sheets"], (
        f"available_sheets ({data['available_sheets']}) must equal on_hand "
        f"({data['on_hand_sheets']}) - reserved ({data['reserved_sheets']})"
    )
    assert data["reserved_sheets"] >= 0
    assert data["on_hand_sheets"] >= 0
