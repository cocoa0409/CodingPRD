"""Entity assertions and domain invariant checkers.

Presence/type checks track the PRD 2.4 common fields and the field shapes
each resource's narrative declares. Money is integer cents (PRD 2.6).
"""
from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

UNIT_TIERS = {"CRITICAL", "STANDARD"}
QUALITY_FLAGS = {"CLEAR", "WATCH"}
SURGE_POSTURES = {"NORMAL", "SURGE"}
LINEN_CATEGORIES = {"FLATWORK", "TERRY", "PATIENT_APPAREL", "ISOLATION"}
STOCK_POSTURES = {"SUFFICIENT", "LOW", "CRITICAL"}
SHRINKAGE_STATUSES = {"NORMAL", "INVESTIGATION"}
CART_CYCLES = {"DAILY", "TWICE_DAILY", "WEEKLY"}
CART_RUN_STATUSES = {"SCHEDULED", "COMPLETED", "DISPUTED", "RECOUNTED", "RECONCILED"}
MANIFEST_STATUSES = {"DISPATCHED", "RETURNED", "RECONCILED"}
INVOICE_STATUSES = {"PROVISIONAL", "FINALIZED", "DISPUTED", "SETTLED"}
COMPLAINT_TYPES = {"STAINS", "TEARS", "FOREIGN_OBJECT", "ODOR", "ISOLATION_BREACH"}
COMPLAINT_STATUSES = {"OPEN", "VERIFIED", "REJECTED", "RESCINDED", "RESOLVED"}
SURGE_SEVERITIES = {"LEVEL_1", "LEVEL_2"}
SURGE_STATUSES = {"DECLARED", "ACTIVE", "CLOSED"}


def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """id / created_at / updated_at / version, per PRD 2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_int_cents(data: Dict[str, Any], field: str, label: str) -> None:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label}.{field} must be integer cents, got {value!r}"
    )


def assert_facility(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    _assert_int_cents(data, "rate_per_lb_cents", "Facility")
    assert isinstance(data["isolation_surcharge_pct"], (int, float))
    assert data.get("monthly_cap_cents") is None or (
        isinstance(data["monthly_cap_cents"], int)
        and not isinstance(data["monthly_cap_cents"], bool)
    )
    assert data["surge_posture"] in SURGE_POSTURES
    _assert_int_cents(data, "credit_balance_cents", "Facility")


def assert_unit(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Unit")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit_tier"] in UNIT_TIERS
    assert data["quality_flag"] in QUALITY_FLAGS


def assert_linen_stock(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "LinenStock")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in LINEN_CATEGORIES
    assert isinstance(data["piece_weight_lbs"], (int, float))
    for field in (
        "unit_cost_cents",
        "max_wash_cycles",
        "reorder_point_pieces",
        "opening_pieces",
        "opening_reserve_pieces",
        "in_circulation",
        "in_wash",
        "reserve_pieces",
        "retired_pieces",
        "lost_pieces",
        "wash_cycles_completed",
    ):
        assert isinstance(data[field], int) and not isinstance(data[field], bool), (
            f"LinenStock.{field} must be an integer, got {data.get(field)!r}"
        )
    assert data["posture"] in STOCK_POSTURES
    assert data["shrinkage_status"] in SHRINKAGE_STATUSES


def assert_par_level(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ParLevel")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("stock_id", ""))
    assert isinstance(data["base_par_quantity"], int)
    assert data["cart_cycle"] in CART_CYCLES
    assert isinstance(data["on_hand"], int)
    assert isinstance(data["effective_par"], int)


def assert_cart_run(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CartExchangeRun")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data.get("manifest_id") is None or is_valid_uuid(data["manifest_id"])
    assert data["status"] in CART_RUN_STATUSES
    assert isinstance(data.get("shortage_flag"), bool)
    assert isinstance(data.get("late_delivery"), bool)
    assert data.get("completed_at") is None or is_iso8601_timestamp(
        data["completed_at"]
    )
    for line in data.get("restock_lines") or []:
        assert is_valid_uuid(line.get("stock_id", ""))
        assert isinstance(line.get("pieces"), int)


def assert_soiled_manifest(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SoiledManifest")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data.get("invoice_id") is None or is_valid_uuid(data["invoice_id"])
    assert data["status"] in MANIFEST_STATUSES
    assert isinstance(data.get("isolation_protocol_ack"), bool)
    assert isinstance(data.get("lines"), list) and data["lines"], (
        "SoiledManifest.lines must be a non-empty list"
    )


def assert_vendor_invoice(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "VendorInvoice")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["status"] in INVOICE_STATUSES
    assert isinstance(data["period_adjusted_patient_days"], int)
    _assert_int_cents(data, "provisional_total_cents", "VendorInvoice")
    _assert_int_cents(data, "credit_total_cents", "VendorInvoice")
    for field in ("final_total_cents", "billed_total_cents"):
        value = data.get(field)
        assert value is None or (
            isinstance(value, int) and not isinstance(value, bool)
        ), f"VendorInvoice.{field} must be null or integer cents, got {value!r}"
    assert data.get("cost_per_apd_cents") is None or isinstance(
        data["cost_per_apd_cents"], (int, float)
    )
    assert isinstance(data.get("created_by_user_id"), str)


def assert_complaint(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("manifest_id", ""))
    assert is_valid_uuid(data.get("stock_id", ""))
    assert data["complaint_type"] in COMPLAINT_TYPES
    assert data["status"] in COMPLAINT_STATUSES
    assert isinstance(data["pieces_affected"], int) and data["pieces_affected"] >= 1
    _assert_int_cents(data, "credit_cents", "Complaint")
    assert data.get("routed_invoice_id") is None or is_valid_uuid(
        data["routed_invoice_id"]
    )


def assert_surge_event(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SurgeEvent")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["severity"] in SURGE_SEVERITIES
    assert isinstance(data["par_multiplier"], (int, float))
    assert data["status"] in SURGE_STATUSES


def restock_totals(restock_lines: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Delivered pieces per stock id, tolerant of zero-piece line omission."""
    totals: Dict[str, int] = {}
    for line in restock_lines or []:
        totals[line["stock_id"]] = totals.get(line["stock_id"], 0) + line["pieces"]
    return totals


def assert_piece_conservation(
    stock: Dict[str, Any],
    on_hand_totals: int,
    opening_total: int,
    net_adjustment_delta: int = 0,
) -> None:
    """PRD 2.7 conservation: every piece is accounted for by the counters.

    in_circulation + in_wash + reserve + retired + lost + pieces sitting on
    units must equal the opening stock plus any net adjustment deltas.
    """
    accounted = (
        stock["in_circulation"]
        + stock["in_wash"]
        + stock["reserve_pieces"]
        + stock["retired_pieces"]
        + stock["lost_pieces"]
        + on_hand_totals
    )
    assert accounted == opening_total + net_adjustment_delta, (
        f"Piece conservation violated: accounted {accounted} != "
        f"{opening_total} + delta {net_adjustment_delta}"
    )
