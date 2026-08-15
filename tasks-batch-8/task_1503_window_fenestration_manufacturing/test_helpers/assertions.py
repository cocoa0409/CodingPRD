"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ORDER_PRODUCTION_STATES = [
    "DRAFT", "CONFIRMED", "RELEASED", "IN_PROGRESS",
    "COMPLETED", "SHIPPED", "DELIVERED", "CANCELLED",
]
ORDER_COMPLIANCE_STATES = ["PENDING", "PROVISIONALLY_COMPLIANT", "CERTIFIED"]
LINE_STATES = [
    "PENDING", "CONFIRMED", "RELEASED", "IN_PRODUCTION",
    "GLASS_HOLD", "COMPLETED", "SHIPPED", "CANCELLED",
]
IG_STATES = ["QUEUED", "GLASS_CUT", "SEALED", "GAS_FILLED", "QC_PASSED", "BROKEN", "SCRAPPED"]
WAVE_STATES = ["PLANNED", "OPEN", "LOCKED", "RELEASED", "CLOSED", "CANCELLED"]
RACK_STATES = ["AVAILABLE", "BOOKED"]
RESERVATION_STATES = ["RESERVED", "LOADING", "SHIPPED", "CANCELLED"]
CLAIM_STATES = [
    "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
    "APPROVED", "DENIED", "FULFILLED", "CLOSED",
]
SHIPMENT_STATES = ["PICKING", "SHIPPED", "DELIVERED"]
LABEL_BASES = ["PROVISIONAL", "CERTIFIED"]
LABEL_COMPLIANCE = ["UNEVALUATED", "PASS", "FAIL"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_dealer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_status"] in ["ACTIVE", "CREDIT_HOLD"]


def assert_catalog_series(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]
    assert isinstance(data["base_rate_cents_per_ui"], int)
    assert isinstance(data["max_united_inches"], int)


def assert_glass_package(data: dict):
    _assert_common(data)
    assert data["spacer_type"] in ["ALUMINUM", "WARM_EDGE"]
    assert data["pane_count"] in (2, 3)


def assert_energy_code_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_window_order(data: dict):
    _assert_common(data)
    assert data["production_status"] in ORDER_PRODUCTION_STATES
    assert data["compliance_status"] in ORDER_COMPLIANCE_STATES
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_price_cents"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["status"] in LINE_STATES
    assert data["shape"] in ["RECTANGLE", "ARCH", "CIRCLE", "TRAPEZOID"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_total_cents"], int)


def assert_energy_label(data: dict):
    _assert_common(data)
    assert data["basis"] in LABEL_BASES
    assert data["status"] in LABEL_BASES
    assert data["compliance"] in LABEL_COMPLIANCE


def assert_ig_unit(data: dict):
    _assert_common(data)
    assert data["status"] in IG_STATES
    assert data["spacer_type"] in ["ALUMINUM", "WARM_EDGE"]
    assert isinstance(data["unit_index"], int) and data["unit_index"] >= 1


def assert_production_wave(data: dict):
    _assert_common(data)
    assert data["status"] in WAVE_STATES
    assert isinstance(data["allocated_units"], int)
    assert data["allocated_units"] <= data["capacity_units"], (
        f"allocated_units {data['allocated_units']} exceeds capacity {data['capacity_units']}"
    )


def assert_shipping_rack(data: dict):
    _assert_common(data)
    assert data["status"] in RACK_STATES
    assert isinstance(data["slot_capacity"], int)


def assert_rack_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in RESERVATION_STATES
    assert isinstance(data["assigned_units"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in CLAIM_STATES
    assert data["component"] in ["FRAME", "IG_SEAL", "GLASS", "HARDWARE", "GRID"]
    assert data["coverage_variant"] in ["COMPONENT", "WHOLE_UNIT"]
    assert isinstance(data["coverage_pct"], int) and 0 <= data["coverage_pct"] <= 100


def assert_service_part_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in SHIPMENT_STATES
    assert data["carrier"] in ["PARCEL", "STANDARD_FREIGHT", "EXPEDITED"]
    assert isinstance(data["shipping_charge_cents"], int)
