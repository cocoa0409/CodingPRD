"""Entity assertions and domain invariant helpers (PRD §2.4, §2.7, §3)."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Weight values are carried to exactly 3 decimals (PRD §2.7); comparisons use a
# tolerance far below one milliquantum so only genuinely equal values pass.
_KG_TOL = 1e-6


def assert_kg(actual, expected, label="weight"):
    """Compare a kilogram quantity carried at 3-decimal half-up precision."""
    assert actual == pytest.approx(expected, abs=_KG_TOL), (
        f"{label}: expected {expected} kg, got {actual}"
    )


def _assert_common_fields(data: dict):
    """Standard system-managed properties on every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Append-only ledger records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert data["steel_index_basis"] in ("CRU_HRC", "CRU_CRC", "LME_STEEL_SCRAP")
    assert isinstance(data["base_index_value"], (int, float))
    assert 0 <= data["pass_through_pct"] <= 1
    assert isinstance(data["active"], bool)


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["material_spec"], str) and data["material_spec"]
    assert isinstance(data["thickness_mm"], (int, float))
    assert isinstance(data["net_weight_kg"], (int, float))
    assert isinstance(data["base_piece_price_cents"], int)
    assert 1 <= data["ppap_required_level"] <= 5
    assert isinstance(data["steel_content_kg"], (int, float))


def assert_die(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["die_code"], str) and data["die_code"]
    assert data["die_type"] in ("PROGRESSIVE", "TRANSFER")
    assert data["total_stations"] >= 1
    assert isinstance(data["rated_tonnage"], int)
    assert isinstance(data["min_bed_width_mm"], int)
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "IN_REPAIR", "RETIRED")
    assert isinstance(data["total_shots_lifetime"], int)
    assert isinstance(data["shots_since_repair"], int)
    assert isinstance(data["repair_threshold_shots"], int)


def assert_press(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["press_code"], str) and data["press_code"]
    assert isinstance(data["tonnage"], int)
    assert isinstance(data["bed_width_mm"], int)
    assert isinstance(data["strokes_per_min"], int)
    assert data["status"] in ("IDLE", "IN_SETUP", "RUNNING")


def assert_part_die_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["die_id"], str)
    assert isinstance(data["qualified"], bool)


def assert_steel_coil(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["coil_number"], str) and data["coil_number"]
    assert isinstance(data["heat_lot_number"], str) and data["heat_lot_number"]
    assert isinstance(data["material_spec"], str)
    assert isinstance(data["thickness_mm"], (int, float))
    assert isinstance(data["received_weight_kg"], (int, float))
    assert isinstance(data["remaining_weight_kg"], (int, float))
    assert data["status"] in (
        "RECEIVED", "APPROVED", "ON_HOLD", "REJECTED", "DEPLETED", "QUARANTINED",
    )


def assert_strip_layout(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["revision"], str)
    assert isinstance(data["strip_width_mm"], (int, float))
    assert isinstance(data["pitch_mm"], (int, float))
    assert isinstance(data["parts_per_strip_segment"], int)
    assert isinstance(data["gross_weight_per_part_kg"], (int, float))
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")


def assert_production_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert data["quantity_ordered"] >= 1
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in (
        "OPEN", "RELEASED", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["quantity_produced_good"], int)
    assert isinstance(data["quantity_scrapped"], int)
    assert data["pricing_variant"] in ("RELEASE_LOCKED", "SHIPMENT_SPOT")


def assert_die_change_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["press_id"], str)
    assert isinstance(data["to_die_id"], str)
    assert is_iso8601_timestamp(data["planned_start"])
    assert is_iso8601_timestamp(data["planned_end"])
    assert isinstance(data["smed_target_minutes"], int)
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_order_id"], str)
    assert isinstance(data["press_id"], str)
    assert isinstance(data["die_id"], str)
    assert isinstance(data["coil_id"], str)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")
    assert isinstance(data["shots_recorded"], int)
    assert isinstance(data["good_count"], int)
    assert isinstance(data["reject_count"], int)


def assert_reject_event(data: dict):
    """RejectEvent is an append-only ledger record (PRD §2.4)."""
    _assert_append_only_fields(data)
    assert isinstance(data["production_run_id"], str)
    assert isinstance(data["station_number"], int)
    assert data["sensor_code"] in (
        "MISFEED", "SHORT_FEED", "PART_EJECT_FAIL", "DOUBLE_BLANK", "SLUG_DETECT",
    )
    assert data["quantity"] >= 1
    assert is_iso8601_timestamp(data["sensed_at"])


def assert_index_publication(data: dict):
    """IndexPublication is an append-only ledger record (PRD §2.4)."""
    _assert_append_only_fields(data)
    assert data["index_code"] in ("CRU_HRC", "CRU_CRC", "LME_STEEL_SCRAP")
    assert is_iso8601_timestamp(data["published_at"])
    assert isinstance(data["value_usd_per_ton"], (int, float))


def assert_price_adjustment(data: dict):
    """PriceAdjustment is an append-only ledger record (PRD §2.4, §3.10)."""
    _assert_append_only_fields(data)
    assert isinstance(data["production_order_id"], str)
    assert data["variant_applied"] in ("RELEASE_LOCKED", "SHIPMENT_SPOT")
    assert isinstance(data["base_index_value"], (int, float))
    assert isinstance(data["applied_index_value"], (int, float))
    assert isinstance(data["adjusted_piece_price_cents"], int)


def assert_outside_processing_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_order_id"], str)
    assert data["operation_type"] in ("PLATING", "HEAT_TREAT", "E_COAT", "DEBURR")
    assert data["quantity_sent"] >= 1
    assert isinstance(data["quantity_returned_good"], int)
    assert isinstance(data["quantity_returned_scrap"], int)
    assert data["status"] in ("SENT", "PARTIAL_RETURN", "CLOSED")


def assert_ppap_submission(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["level"], int)
    assert isinstance(data["submission_revision"], int)
    assert data["submission_revision"] >= 1
    assert isinstance(data["control_plan_attached"], bool)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED")


def assert_layered_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["press_id"], str)
    assert data["audit_tier"] in (1, 2, 3)
    assert is_iso8601_timestamp(data["scheduled_date"])
    assert data["result"] in ("PENDING", "PASS", "FAIL")
    assert isinstance(data["findings_count"], int)
