"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC datetime, accepting both the `Z` form and the
    three-fractional-digit form (PRD pins fractional digits only for
    created_at/updated_at in §2.5 and api_request_timestamp in §2.2; other
    datetime fields may be rendered either way by a faithful server)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str) -> None:
    """Assert two ISO 8601 datetimes denote the same instant, regardless of
    fractional-digit rendering (".000Z" vs "Z")."""
    actual_dt = _parse_instant(actual)
    expected_dt = _parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"instant mismatch: {actual!r} != {expected_iso!r}"
    )


def assert_common_fields(data: dict):
    """PRD §2.5: every top-level resource has id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_shop(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    for k in (
        "weekly_crew_hours_capacity", "horizon_weeks", "bay_count", "truck_fleet_size",
        "labor_rate_cents_per_hour", "overtime_multiplier_bp", "overhead_pct_bp",
        "margin_pct_bp", "committed_crew_hours", "capacity_ratio_bp",
        "inventory_value_cents", "epoch_index",
    ):
        assert isinstance(data.get(k), int), f"{k} must be int, got {data.get(k)!r}"
    assert data.get("posture") in ("OPEN", "TIGHT", "SATURATED")


def assert_client(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert isinstance(data.get("company_name"), str)
    assert isinstance(data.get("credit_limit_cents"), int)
    assert isinstance(data.get("outstanding_cents"), int)


def assert_design_package(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data.get("show_title"), str)
    assert isinstance(data.get("drawing_revision"), int) and data["drawing_revision"] >= 1
    assert data.get("status") in ("CURRENT", "SUPERSEDED")


def assert_takeoff(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("design_package_id", ""))
    assert isinstance(data.get("labor_hours_est"), int)
    assert isinstance(data.get("pinned_package_revision"), int)
    assert isinstance(data.get("materials_subtotal_cents"), int)
    assert data.get("status") in ("DRAFT", "LOCKED")


def assert_takeoff_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("takeoff_id", ""))
    assert isinstance(data.get("material_code"), str)
    assert isinstance(data.get("quantity"), int)
    assert data.get("source") in ("PURCHASE", "STOCK")
    assert isinstance(data.get("waste_pct_bp"), int)
    assert isinstance(data.get("applied_unit_cost_cents"), int)
    assert isinstance(data.get("line_total_cents"), int)


def assert_bid(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("design_package_id", ""))
    assert data.get("pricing_variant") in ("DETAILED", "ROM")
    assert isinstance(data.get("bays_required"), int)
    assert isinstance(data.get("validity_days"), int)
    assert isinstance(data.get("pinned_drawing_revision"), int)
    assert isinstance(data.get("price_cents"), int)
    assert isinstance(data.get("round_no"), int) and data["round_no"] >= 1
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "COUNTERED", "WITHDRAWN", "EXPIRED",
    )


def assert_production(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert is_valid_uuid(data.get("bid_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))
    assert isinstance(data.get("committed_crew_hours"), int)
    assert isinstance(data.get("bays_required"), int)
    assert isinstance(data.get("required_review_scopes"), list)
    assert isinstance(data.get("applied_drawing_revision"), int)
    assert isinstance(data.get("current_price_cents"), int)
    assert data.get("status") in (
        "SCHEDULED", "IN_BUILD", "ON_HOLD", "BUILT", "LOADED_IN", "STRUCK", "CLOSED",
    )


def assert_engineering_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert data.get("scope") in ("STRUCTURAL", "AUTOMATION")
    assert isinstance(data.get("prepared_by_user_id"), str)
    assert isinstance(data.get("sf_static"), (int, float))
    assert isinstance(data.get("round_no"), int) and data["round_no"] >= 1
    assert data.get("status") in ("PENDING", "APPROVED", "REVISION_REQUIRED")


def assert_finish_sample(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert isinstance(data.get("finish_code"), str)
    assert isinstance(data.get("texture_ref"), str)
    assert isinstance(data.get("round_no"), int) and data["round_no"] >= 1
    assert data.get("status") in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_change_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert isinstance(data.get("new_drawing_revision"), int)
    assert isinstance(data.get("delta_materials_cents"), int)
    assert isinstance(data.get("delta_labor_hours"), int)
    assert isinstance(data.get("delta_load_in_days"), int)
    assert isinstance(data.get("delta_price_cents"), int)
    assert isinstance(data.get("co_no"), int) and data["co_no"] >= 1
    assert data.get("status") in ("PROPOSED", "APPROVED", "REJECTED", "WITHDRAWN")


def assert_bay_reservation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert isinstance(data.get("bay_slot"), int)
    assert data.get("status") in ("ACTIVE", "RELEASED")


def assert_stock_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert isinstance(data.get("material_code"), str)
    assert data.get("condition_grade") in ("A", "B", "C")
    assert isinstance(data.get("quantity_on_hand"), int)
    assert data.get("origin") in ("PURCHASED", "RECLAIMED")
    assert isinstance(data.get("replacement_cost_cents"), int)
    assert isinstance(data.get("reuse_unit_cost_cents"), int)
    assert isinstance(data.get("reuse_value_cents"), int)
    assert isinstance(data.get("replacement_value_cents"), int)
    assert data.get("status") in ("ACTIVE", "DEPLETED")


def assert_transport_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("production_id", ""))
    assert isinstance(data.get("truck_count"), int)
    assert isinstance(data.get("install_crew_hours"), int)
    assert data.get("status") in ("PLANNED", "CONFIRMED", "EXECUTED", "CANCELLED")
