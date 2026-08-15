"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §2.10)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssessmentStatus,
    BillingStatus,
    ClaimType,
    CustomerType,
    DisplacementPlanStatus,
    ExecutionStatus,
    InvoiceStatus,
    LotKind,
    MaterialGrade,
    MaterialLotStatus,
    QuoteStatus,
    RouteSheetStatus,
    SlopeSeverity,
    StripingStatus,
    WarrantyClaimStatus,
    WarrantyRecordStatus,
    WeatherSource,
)


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["customer_type"] in [e.value for e in CustomerType]
    assert isinstance(data["email"], str)
    assert isinstance(data["phone"], str)


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert data["lot_kind"] in [e.value for e in LotKind]
    assert "current_area_sqft" in data
    assert "open_quote_id" in data
    assert "last_completed_seal_on" in data
    assert "next_seal_eligible_on" in data


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert data["measured_area_sqft"] > 0
    assert data["crack_linear_ft"] >= 0
    assert isinstance(data["pothole_count"], int) and data["pothole_count"] >= 0
    assert data["pothole_area_sqft"] >= 0
    assert data["oil_spot_area_sqft"] >= 0
    assert data["slope_severity"] in [e.value for e in SlopeSeverity]
    assert isinstance(data["pavement_condition_index"], int)
    assert 0 <= data["pavement_condition_index"] <= 100
    assert "submitted_at" in data
    assert data["status"] in [e.value for e in AssessmentStatus]


def assert_material(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_name"], str) and len(data["product_name"]) > 0
    assert data["grade"] in [e.value for e in MaterialGrade]
    assert data["coverage_sqft_per_gallon"] > 0
    assert isinstance(data["min_apply_temp_f"], (int, float))
    assert 0 <= data["max_precip_probability_pct"] <= 100
    assert data["cure_hours_vehicle"] > 0
    assert data["reapplication_months"] > 0
    assert data["warranty_months"] > 0
    assert data["price_per_gallon_cents"] > 0


def assert_material_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["material_id"], str)
    assert data["delivered_gallons"] > 0
    assert data["reserved_gallons"] >= 0
    assert data["consumed_gallons"] >= 0
    assert data["wasted_gallons"] >= 0
    assert data["on_hand_gallons"] >= 0
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["received_on"], str)
    assert data["reorder_threshold_gallons"] >= 0
    assert isinstance(data["reorder_flag"], bool)
    assert data["status"] in [e.value for e in MaterialLotStatus]


def assert_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_name"], str) and len(data["crew_name"]) > 0
    assert isinstance(data["home_zone"], str)
    assert data["daily_capacity_sqft"] > 0
    assert isinstance(data["active"], bool)


def assert_route_sheet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["service_date"], str)
    assert data["capacity_sqft"] > 0
    assert data["booked_sqft"] >= 0
    assert data["total_drive_minutes"] >= 0
    assert "open_capacity_sqft" in data
    assert data["status"] in [e.value for e in RouteSheetStatus]


def assert_quote(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["assessment_id"], str)
    assert isinstance(data["material_id"], str)
    for flag in ("include_crack_fill", "include_patch", "include_seal", "include_striping"):
        assert isinstance(data[flag], bool)
    assert data["coats"] in (1, 2)
    for money in (
        "seal_line_cents",
        "crack_line_cents",
        "patch_line_cents",
        "striping_line_cents",
        "subtotal_cents",
        "discount_cents",
        "mobilization_fee_cents",
        "total_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, (
            f"{money} must be integer cents, got {data.get(money)!r}"
        )
    assert "sent_at" in data
    assert "expires_on" in data
    assert data["status"] in [e.value for e in QuoteStatus]


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["quote_id"], str)
    assert "warranty_claim_id" in data
    assert "route_sheet_id" in data
    assert "material_lot_id" in data
    for flag in ("include_crack_fill", "include_patch", "include_seal", "include_striping"):
        assert isinstance(data[flag], bool)
    assert data["coats"] in (1, 2)
    assert data["material_grade"] in [e.value for e in MaterialGrade]
    assert data["quoted_area_sqft"] > 0
    assert isinstance(data["quoted_total_cents"], int) and data["quoted_total_cents"] >= 0
    assert "scheduled_date" in data
    assert data["reserved_gallons"] >= 0
    assert data["execution_status"] in [e.value for e in ExecutionStatus]
    assert data["billing_status"] in [e.value for e in BillingStatus]
    assert data["striping_status"] in [e.value for e in StripingStatus]


def assert_displacement_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["vehicles_to_move"], int) and data["vehicles_to_move"] >= 0
    assert "notice_sent_at" in data
    assert is_iso8601_timestamp(data.get("access_block_start", "")), (
        f"access_block_start must be ISO 8601 UTC, got {data.get('access_block_start')!r}"
    )
    assert is_iso8601_timestamp(data.get("access_block_end", "")), (
        f"access_block_end must be ISO 8601 UTC, got {data.get('access_block_end')!r}"
    )
    assert data["status"] in [e.value for e in DisplacementPlanStatus]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        assert isinstance(line.get("label"), str)
        assert isinstance(line.get("amount_cents"), int) and line["amount_cents"] >= 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["fuel_surcharge_cents"], int) and data["fuel_surcharge_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert "issued_at" in data
    assert "paid_at" in data
    assert data["status"] in [e.value for e in InvoiceStatus]


def assert_warranty_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["warranty_months"], int) and data["warranty_months"] > 0
    assert isinstance(data["started_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in [e.value for e in WarrantyRecordStatus]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["warranty_record_id"], str)
    assert data["claim_type"] in [e.value for e in ClaimType]
    assert isinstance(data["description"], str)
    assert "investigated_by" in data
    assert "repair_work_order_id" in data
    assert data["status"] in [e.value for e in WarrantyClaimStatus]


def assert_weather_snapshot(data: dict):
    """Append-only weather event: id + created_at present; version/updated_at absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "weather snapshots must not carry version"
    assert "updated_at" not in data, "weather snapshots must not carry updated_at"
    assert isinstance(data["target_date"], str)
    assert isinstance(data["min_temp_f"], (int, float))
    assert isinstance(data["max_temp_f"], (int, float))
    assert 0 <= data["precip_probability_pct"] <= 100
    assert data["precipitation_mm"] >= 0
    assert data["source"] in [e.value for e in WeatherSource]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_lot_ledger_conserved(lot: dict):
    """delivered == reserved + consumed + wasted + on_hand (PRD §2.9)."""
    total = (
        lot["reserved_gallons"]
        + lot["consumed_gallons"]
        + lot["wasted_gallons"]
        + lot["on_hand_gallons"]
    )
    assert abs(total - lot["delivered_gallons"]) < 1e-9, (
        f"lot ledger drift: {lot['delivered_gallons']} delivered vs "
        f"{lot['reserved_gallons']}r + {lot['consumed_gallons']}c + "
        f"{lot['wasted_gallons']}w + {lot['on_hand_gallons']}h"
    )
    assert lot["reorder_flag"] == (lot["on_hand_gallons"] <= lot["reorder_threshold_gallons"]), (
        f"reorder_flag {lot['reorder_flag']} inconsistent with on_hand "
        f"{lot['on_hand_gallons']} vs threshold {lot['reorder_threshold_gallons']}"
    )


def assert_sheet_capacity_conserved(sheet: dict):
    """capacity_sqft == booked_sqft + open_capacity_sqft (PRD §2.10)."""
    assert sheet["capacity_sqft"] == sheet["booked_sqft"] + sheet["open_capacity_sqft"], (
        f"capacity ledger drift: {sheet['capacity_sqft']} vs "
        f"{sheet['booked_sqft']} booked + {sheet['open_capacity_sqft']} open"
    )


def assert_instant_equal(actual: str, expected_iso: str):
    """Compare two ISO 8601 UTC instants by value, tolerating fractional-second
    rendering differences (the PRD pins millisecond precision only on
    created_at/updated_at)."""
    def _parse(v: str) -> datetime:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))

    assert is_iso8601_timestamp(actual), f"not an ISO 8601 UTC timestamp: {actual!r}"
    assert _parse(actual) == _parse(expected_iso), (
        f"expected instant {expected_iso}, got {actual}"
    )
