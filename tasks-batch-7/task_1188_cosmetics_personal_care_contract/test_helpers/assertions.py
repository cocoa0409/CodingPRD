"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def _assert_append_only_fields(data: dict):
    """PRD §2.4: append-only quality records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in ("STANDARD", "PRESTIGE")
    assert isinstance(data["minimum_run_units"], int) and data["minimum_run_units"] >= 1
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "ACTIVE", "RETIRED",
    )
    assert data["ownership"] in ("CUSTOMER_OWNED", "MANUFACTURER_OWNED")
    assert data["confidentiality"] in ("STANDARD", "EXCLUSIVE")
    assert data["product_class"] in ("SKIN", "HAIR", "BABY", "SUN")
    assert isinstance(data["version_seq"], int) and data["version_seq"] >= 1
    assert isinstance(data["ingredients"], list)


def assert_review(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "CHANGES_REQUESTED")
    assert data["review_scope"] in ("INCI_LIST", "LABEL_ARTWORK")


def assert_component(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in (
        "RAW_MATERIAL", "BULK_FRAGRANCE", "COLORANT", "PRIMARY_PACK", "SECONDARY_PACK",
    )
    assert data["supply_mode"] in ("MANUFACTURER_SUPPLIED", "CUSTOMER_SUPPLIED")


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "DEPLETED")
    assert data["sensorial_profile"] in ("WITHIN_SPEC", "MINOR_VARIANT")
    assert data["variant_waiver"] in ("NOT_REQUIRED", "PENDING", "WAIVED", "REJECTED")
    assert_lot_quantity_conservation(data)


def assert_lot_quantity_conservation(data: dict):
    """PRD §3.1: received == available + reserved + consumed at all times."""
    total = data["quantity_available"] + data["quantity_reserved"] + data["quantity_consumed"]
    assert abs(total - data["quantity_received"]) < 1e-6, (
        f"lot partition drifted: {data['quantity_received']} != "
        f"{data['quantity_available']} + {data['quantity_reserved']} + {data['quantity_consumed']}"
    )


def assert_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "IN_PRODUCTION", "FILLING", "COMPLETED", "ON_HOLD", "CANCELLED",
    )
    assert isinstance(data["requested_units"], int)
    assert isinstance(data["quote_total_cents"], int)


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "MIXING", "IPC_FAILED", "IPC_PASSED",
        "RELEASED_TO_FILLING", "CONSUMED", "REJECTED",
    )
    assert isinstance(data["failed_check_count"], int) and data["failed_check_count"] >= 0


def assert_ipc_check(data: dict):
    _assert_append_only_fields(data)
    assert data["check_type"] in ("VISCOSITY", "PH")
    assert data["result"] in ("PASS", "FAIL")


def assert_allocation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RESERVED", "RELEASED", "CONSUMED")
    assert data["quantity"] > 0


def assert_shortfall(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "OPEN", "COMMITMENT_RECEIVED", "CLOSED_RESOLVED", "ESCALATED", "CLOSED_VOID",
    )


def assert_line(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("IDLE", "RUNNING", "CLEANING")


def assert_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 1


def assert_chamber(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["capacity_studies"], int) and data["capacity_studies"] >= 1
    assert isinstance(data["active_study_count"], int) and data["active_study_count"] >= 0


def assert_study(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("IN_PROGRESS", "COMPLETED_PASS", "COMPLETED_FAIL")
    assert data["study_type"] in ("PRESERVATIVE_EFFICACY", "ACCELERATED", "REAL_TIME")
    assert isinstance(data["required_intervals"], list)


def assert_reading(data: dict):
    _assert_append_only_fields(data)
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["interval_index"], int)
