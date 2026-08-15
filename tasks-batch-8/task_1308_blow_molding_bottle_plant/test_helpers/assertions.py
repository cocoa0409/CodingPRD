"""Entity assertions and domain invariant checkers.

Field checks follow PRD section 2.5 (common system-managed properties) and the
per-entity field narratives of PRD section 3.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["default_logistics_mode"] in ("WAREHOUSE", "BLOW_ON_SITE")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_freight_rate_card(data: dict):
    _assert_common(data)
    assert isinstance(data["lane_code"], str) and data["lane_code"]
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_bottle_spec(data: dict):
    _assert_common(data)
    assert data["resin_type"] in ("PET", "HDPE", "PP")
    assert data["color_contrast_class"] in ("CLEAR", "LIGHT", "DARK")
    assert data["label_type"] in ("NONE", "PRESSURE_SENSITIVE", "SHRINK_SLEEVE", "IN_MOLD")
    assert data["status"] in ("DRAFT", "SUBMITTED", "IN_QUALIFICATION",
                              "REVISION_REQUESTED", "QUALIFIED", "PRODUCTION_ACTIVE",
                              "RETIRED")
    assert isinstance(data["content_revision"], int) and data["content_revision"] >= 1
    assert isinstance(data["requires_inline_labeler"], bool)
    assert data["requires_inline_labeler"] == (data["label_type"] != "NONE")


def assert_qualification_run(data: dict):
    _assert_common(data)
    assert isinstance(data["round_no"], int) and data["round_no"] >= 1
    assert isinstance(data["spec_revision_pinned"], int)
    assert data["status"] in ("PLANNED", "EXECUTED", "CUSTOMER_REVIEW",
                              "APPROVED", "REJECTED")


def assert_mold(data: dict):
    _assert_common(data)
    assert isinstance(data["base_cavities"], int) and data["base_cavities"] >= 1
    assert isinstance(data["effective_cavities"], int)
    assert isinstance(data["active_blockout_count"], int)
    assert data["status"] in ("STORAGE", "INSTALLED")


def assert_cavity_blockout(data: dict):
    _assert_common(data)
    assert isinstance(data["cavity_index"], int) and data["cavity_index"] >= 1
    assert data["reason"] in ("DAMAGE", "CONTAMINATION_HOLD", "PREVENTIVE", "QUALITY_HOLD")
    assert data["status"] in ("OPEN", "CLEARED")


def assert_machine_line(data: dict):
    _assert_common(data)
    assert isinstance(data["has_inline_labeler"], bool)
    assert data["status"] in ("IDLE", "CHANGEOVER", "RUNNING")
    assert data.get("last_color_class") in ("CLEAR", "LIGHT", "DARK", None)


def assert_schedule_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["planned_start"] < data["planned_end"]


def assert_material_lot(data: dict):
    _assert_common(data)
    assert data["material_type"] in ("RESIN", "COLORANT")
    assert data["status"] in ("QUARANTINED", "RELEASED", "IN_USE", "DEPLETED", "REJECTED")
    assert isinstance(data["received_kg"], (int, float))
    assert isinstance(data["available_kg"], (int, float))
    assert isinstance(data["consumed_kg"], (int, float))
    assert isinstance(data["purge_wasted_kg"], (int, float))


def assert_production_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SCHEDULED", "RELEASED", "RUNNING", "HELD",
                              "COMPLETED", "CANCELLED")
    assert isinstance(data["quantity_ordered"], int)
    assert data["logistics_mode"] in ("WAREHOUSE", "BLOW_ON_SITE")


def assert_production_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED", "VOIDED")
    assert isinstance(data["cavities_active_at_start"], int)


def assert_quality_test_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SAMPLED", "ACCEPTED", "REJECTED",
                              "SCRAPPED", "VOIDED")
    assert isinstance(data["lot_size"], int)
    assert isinstance(data["sample_size_n"], int)
    assert isinstance(data["accept_number_leak"], int)
    assert isinstance(data["accept_number_drop"], int)


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "BOOKED", "LOADING", "IN_TRANSIT",
                              "DELIVERED", "CANCELLED")
    assert data["shipment_mode"] in ("FINISHED_BOTTLES", "PREFORMS")
    assert isinstance(data["quantity"], int)


def assert_dock_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "OCCUPIED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert 1 <= data["dock_door"] <= 3


def assert_material_lot_conservation(lot: dict):
    """PRD section 3.4: available_kg is always what remains of the received
    quantity after consumption and purge waste, and never goes negative."""
    assert lot["available_kg"] >= 0, "available_kg must never be negative"
    total = lot["available_kg"] + lot["consumed_kg"] + lot["purge_wasted_kg"]
    assert abs(total - lot["received_kg"]) < 1e-6, (
        f"lot conservation violated: {lot['received_kg']} != "
        f"{lot['available_kg']} + {lot['consumed_kg']} + {lot['purge_wasted_kg']}"
    )


def assert_order_stock_conservation(summary: dict):
    """PRD section 3.5: quantity_unallocated is quantity_accepted minus
    reserved minus shipped."""
    expected = summary["quantity_accepted"] - summary["quantity_reserved"] \
        - summary["quantity_shipped"]
    assert summary["quantity_unallocated"] == expected, (
        f"order stock conservation violated: unallocated "
        f"{summary['quantity_unallocated']} != {expected}"
    )
