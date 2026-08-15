"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

RO_STATUSES = [
    "RECEIVED", "IN_INSPECTION", "QUOTE_IN_PROGRESS", "AUTHORIZED", "IN_REPAIR",
    "IN_TEST", "READY_FOR_CERT", "COMPLETE", "CLOSED", "CANCELLED",
]
QUOTE_STATUSES = [
    "DRAFT", "ISSUED", "REVISION_REQUESTED", "APPROVED", "DECLINED", "EXPIRED",
    "SUPERSEDED", "CANCELLED",
]
POOL_STATUSES = ["IN_POOL", "RESERVED", "ISSUED", "WITHDRAWN"]
WINDOW_POSTURES = ["NORMAL", "SURGE", "FULL"]


def _parse_instant(value: str) -> datetime:
    txt = str(value).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str):
    """Compare two ISO-8601 timestamps by instant value.

    PRD §2.4 pins the logical clock's reading and §3.6 pins derived stamps
    (`issued_at`, `expires_at` + 14 days) to instants; the string layout of
    these fields (e.g. millisecond rendering) is not pinned by the PRD, so the
    assertion compares instants, not exact strings.
    """
    assert is_iso8601_timestamp(actual), f"{actual!r} is not an ISO 8601 UTC timestamp"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{actual!r} does not equal {expected_iso!r} as instants"
    )


def _assert_common_fields(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_nullable_uuid(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_valid_uuid(value), f"{field} must be null or a UUID"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["warranty_terms_days"], int)
    assert isinstance(data["pool_program"], bool)
    assert isinstance(data["pool_available_count"], int) and data["pool_available_count"] >= 0


def assert_asset(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["equipment_class"] in ("PUMP", "GENERAL_VALVE", "SAFETY_RELIEF_VALVE")
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["model"], str) and data["model"]
    assert data["test_standard"] in ("API_610_PER_POINT", "SHOP_WEIGHTED_AVG")


def assert_repair_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("asset_id", ""))
    _assert_nullable_uuid(data, "warranty_parent_ro_id")
    assert data["failure_mode"] in (
        "SEAL_LEAK", "BEARING_FAILURE", "CAVITATION", "SEAT_LEAKAGE",
        "SPRING_DRIFT", "OTHER",
    )
    assert isinstance(data["failure_description"], str)
    assert data["intake_priority"] in ("STANDARD", "SURGE")
    assert isinstance(data["planned_start_date"], str)
    assert isinstance(data["planned_end_date"], str)
    assert isinstance(data["estimated_bay_hours"], int) and data["estimated_bay_hours"] > 0
    assert isinstance(data["exchange_requested"], bool)
    assert data["status"] in RO_STATUSES
    assert isinstance(data["warranty_case"], bool)
    assert isinstance(data["repeat_failure_flag"], bool)
    assert isinstance(data["repair_round"], int) and data["repair_round"] >= 0
    assert data["repair_outcome"] in ("NONE", "FIRST_TIME_FIX", "RE_REPAIR")
    assert isinstance(data["requires_certification"], bool)
    assert data.get("assembled_by_id") is None or isinstance(data["assembled_by_id"], str)
    _assert_nullable_uuid(data, "capacity_window_id")
    assert isinstance(data["quote_attention_required"], bool)
    assert data.get("invoiced_total_cents") is None or isinstance(data["invoiced_total_cents"], int)
    assert data.get("closed_at") is None or is_iso8601_timestamp(data["closed_at"])


def assert_inspection_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert isinstance(data["findings_summary"], str)
    assert data["recommended_action"] in ("REPAIR", "REPLACE", "RETURN_UNREPAIRED")
    assert isinstance(data["estimated_labor_hours"], (int, float))
    assert isinstance(data["part_lines"], list)
    assert data["report_status"] in ("DRAFT", "FINALIZED")
    assert isinstance(data["inspector_id"], str) and data["inspector_id"]


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert is_valid_uuid(data.get("capacity_window_id", ""))
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in QUOTE_STATUSES
    assert isinstance(data["labor_hours"], (int, float))
    assert isinstance(data["labor_rate_cents"], int)
    assert isinstance(data["part_lines"], list)
    assert data["pricing_variant"] in ("COMMERCIAL", "WARRANTY")
    assert isinstance(data["surge_multiplier_applied"], (int, float))
    assert isinstance(data["parts_subtotal_cents"], int)
    assert isinstance(data["labor_cents"], int)
    assert isinstance(data["total_cents"], int)
    _assert_nullable_uuid(data, "supersedes_quote_id")
    assert data.get("issued_at") is None or is_iso8601_timestamp(data["issued_at"])
    assert data.get("expires_at") is None or is_iso8601_timestamp(data["expires_at"])


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["description"], str)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["aftermarket_allowed"], bool)
    assert data["status"] in ("ACTIVE", "OBSOLETE")
    _assert_nullable_uuid(data, "superseded_by_id")


def assert_pool_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("asset_id", ""))
    assert data["pool_status"] in POOL_STATUSES
    _assert_nullable_uuid(data, "reserved_for_ro_id")


def assert_test_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert isinstance(data["run_number"], int) and data["run_number"] >= 1
    assert data["test_type"] in ("PERFORMANCE_CURVE", "HYDROSTATIC", "POP_TEST")
    assert isinstance(data["measured_points"], list) and data["measured_points"]
    assert isinstance(data["max_deviation_pct"], (int, float))
    assert isinstance(data["weighted_deviation_pct"], (int, float))
    assert data["verdict"] in ("PASS", "FAIL")
    assert isinstance(data["tested_by_id"], str) and data["tested_by_id"]


def assert_certification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert isinstance(data["tag_number"], str) and data["tag_number"].startswith("SVT-")
    assert isinstance(data["set_pressure_psig"], (int, float))
    assert data["seat_leakage_class"] in ("CLASS_IV", "CLASS_V", "CLASS_VI")
    assert isinstance(data["certified_by_id"], str) and data["certified_by_id"]
    assert data["cert_status"] in ("ISSUED", "VOIDED")
    assert data.get("void_reason") is None or isinstance(data["void_reason"], str)


def assert_capacity_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data["bay_hours_capacity"], int) and data["bay_hours_capacity"] > 0
    assert isinstance(data["bay_hours_reserved"], int) and data["bay_hours_reserved"] >= 0
    assert data["window_posture"] in WINDOW_POSTURES


def assert_window_posture_consistent(data: dict):
    """Domain invariant (PRD §3.6): posture derives from reserved vs capacity —
    FULL when reserved >= capacity; SURGE when reserved >= the smallest whole
    number that is at least eighty percent of capacity; otherwise NORMAL."""
    capacity = data["bay_hours_capacity"]
    reserved = data["bay_hours_reserved"]
    # Exact integer arithmetic: smallest h with h >= 0.8 * capacity.
    surge_min = -(-(4 * capacity) // 5)  # ceil(4*capacity/5) without floats
    if reserved >= capacity:
        expected = "FULL"
    elif reserved >= surge_min:
        expected = "SURGE"
    else:
        expected = "NORMAL"
    assert data["window_posture"] == expected, (
        f"posture {data['window_posture']} inconsistent with reserved={reserved} "
        f"capacity={capacity} (expected {expected})"
    )


def assert_quote_money_consistency(data: dict):
    """Domain invariant (PRD §3.5): total is the half-up-rounded product of the
    pre-surge amount and the stored multiplier."""
    pre_surge = data["parts_subtotal_cents"] + data["labor_cents"]
    expected = pre_surge * data["surge_multiplier_applied"]
    assert abs(data["total_cents"] - expected) <= 0.5 + 1e-6, (
        f"total_cents {data['total_cents']} inconsistent with subtotal+labor "
        f"{pre_surge} x multiplier {data['surge_multiplier_applied']}"
    )
