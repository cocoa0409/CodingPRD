"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["credit_used_cents"], int)
    assert data["delivery_terms"] in ("FOB_PLANT", "DELIVERED")


def assert_engineer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["seal_authority"] in ("TRUSS_ONLY", "TRUSS_AND_PANEL")


def assert_job(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "QUOTED", "CONFIRMED", "IN_PRODUCTION", "SHIPPING", "COMPLETED", "CANCELLED",
    )
    assert data["posture"] in ("GREEN", "AT_RISK", "BLOCKED")
    assert isinstance(data["invoiced_cents"], int)
    assert isinstance(data["credit_issued_cents"], int)


def assert_design(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SEAL_REQUESTED", "SEALED", "SUPERSEDED", "VOID")
    assert isinstance(data["revision_no"], int)
    assert data["component_type"] in ("FLOOR_TRUSS", "ROOF_TRUSS", "WALL_PANEL")


def assert_cut_list(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("EXPLODED", "RELEASED", "RECONCILING", "SUPERSEDED", "CLOSED")
    assert isinstance(data["total_pieces"], int)
    assert isinstance(data["total_plates"], int)


def assert_cut_list_line(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "CUT", "SCRAPPED")
    assert data["dimension"] in ("L2X4", "L2X6", "L2X8")


def assert_jig_setup(data: dict):
    """JigSetup is immutable: carries only id and created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "JigSetup must not expose updated_at"
    assert "version" not in data, "JigSetup must not expose version"
    assert data["component_type_supported"] in ("FLOOR_TRUSS", "ROOF_TRUSS", "WALL_PANEL")
    assert data["plate_class"] in ("P20", "P18", "P16")


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "QUARANTINED", "DEPLETED")
    assert data["lot_kind"] in ("LUMBER", "PLATE")


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")


def assert_crane(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")
    assert data["crane_class"] in ("LIGHT", "STANDARD", "HEAVY")


def assert_crane_slot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")
    assert data["purpose"] in ("BUILD_PICK", "LOAD_PICK")


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED", "CUTTING", "ASSEMBLY", "BUILT", "QC_PASSED", "QC_FAILED",
        "REWORK", "STAGED", "LOADED", "CANCELLED",
    )
    assert isinstance(data["build_sequence_no"], int)


def assert_load(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "STAGED", "LOADING", "DISPATCHED", "DELIVERED", "RETURNED",
        "RESCHEDULED", "CLAIM_HOLD", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["provisional_freight_cents"], int)


def assert_bundle(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PACKED", "LOADED", "DELIVERED", "RETURNED", "DAMAGED", "SUPERSEDED")


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "FILED", "TRIAGED", "APPROVED_REBUILD", "APPROVED_CREDIT",
        "REBUILD_IN_PROGRESS", "DENIED", "SETTLED", "VOID",
    )


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "IMPACT_ASSESSED", "APPROVED", "REJECTED", "WITHDRAWN", "APPLIED",
    )


def assert_lumber_lot_conservation(data: dict):
    """PRD conservation ledger: the four lumber buckets partition the received volume."""
    total = (
        float(data["available_bf"])
        + float(data["reserved_bf"])
        + float(data["consumed_bf"])
        + float(data["scrapped_bf"])
    )
    assert total == pytest.approx(float(data["received_board_feet"]), abs=0.01), (
        f"lumber conservation violated: {data['available_bf']} + {data['reserved_bf']} "
        f"+ {data['consumed_bf']} + {data['scrapped_bf']} != {data['received_board_feet']}"
    )
