"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be a positive int"


def assert_grower(data: dict):
    _assert_common(data, "GrowerAccount")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["credit_used_cents"], int)
    assert isinstance(data["prepay_balance_cents"], int)
    assert data["credit_status"] in ["ACTIVE", "CREDIT_HOLD", "SUSPENDED"]


def assert_field(data: dict):
    _assert_common(data, "Field")
    assert data["acres"] > 0
    assert data["watershed_zone"] in ["STANDARD", "PROTECTED", "CRITICAL"]


def assert_soil_test(data: dict):
    _assert_common(data, "SoilTest")
    assert data["status"] in ["REQUESTED", "SAMPLED", "RESULTED"]


def assert_recommendation(data: dict):
    _assert_common(data, "Recommendation")
    assert data["crop"] in ["CORN", "SOYBEAN", "WHEAT"]
    assert data["rate_variant"] in ["BUILD_RATE", "MAINTENANCE_RATE"]
    assert data["status"] in ["DRAFT", "PENDING_REVIEW", "APPROVED", "SUPERSEDED", "EXPIRED"]


def assert_nutrient_plan(data: dict):
    _assert_common(data, "NutrientManagementPlan")
    assert data["n_cap_lbs_per_acre"] > 0
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "SUSPENDED", "EXPIRED"]


def assert_permit(data: dict):
    _assert_common(data, "EnvironmentalPermit")
    assert data["permit_type"] in ["FERTILIZER_STORAGE", "BLENDER_SITE", "ANHYDROUS_STORAGE"]
    assert data["status"] in ["APPLICATION", "UNDER_INSPECTION", "ACTIVE", "EXPIRED", "RENEWAL", "REVOKED"]


def assert_product(data: dict):
    _assert_common(data, "Product")
    assert 0 <= data["analysis_n_pct"] <= 100
    assert 0 <= data["analysis_p2o5_pct"] <= 100
    assert 0 <= data["analysis_k2o_pct"] <= 100
    assert data["form"] in ["DRY", "LIQUID"]


def assert_price_sheet(data: dict):
    _assert_common(data, "PriceSheet")
    assert data["season"] in ["FALL", "SPRING", "SUMMER", "IN_SEASON"]
    assert data["price_per_ton_cents"] > 0
    assert data["status"] in ["DRAFT", "PUBLISHED", "EXPIRED"]


def assert_inventory_lot(data: dict):
    _assert_common(data, "InventoryLot")
    assert data["received_tons"] > 0


def assert_prepay_program(data: dict):
    _assert_common(data, "PrepayProgram")
    assert data["season"] in ["FALL", "SPRING"]
    assert data["status"] in ["ENROLLMENT_OPEN", "ENROLLMENT_CLOSED", "SETTLED"]


def assert_prepay_contract(data: dict):
    _assert_common(data, "PrepayContract")
    assert data["committed_tons"] > 0
    assert data["status"] in ["SIGNED", "PARTIALLY_FUNDED", "FUNDED", "DEFAULTED", "CLOSED_SETTLED", "REFUNDED"]


def assert_blend_order(data: dict):
    _assert_common(data, "BlendOrder")
    assert data["price_mode"] in ["FLOATING", "PRICE_LOCKED"]
    assert data["fulfillment_status"] in [
        "QUOTED", "BOOKED", "SCHEDULED", "BATCHED", "LOADED",
        "DELIVERED", "APPLIED_CONFIRMED", "CLOSED", "CANCELLED",
    ]
    assert data["payment_status"] in [
        "UNPAID", "PREPAY_APPLIED", "CREDIT_APPROVED", "INVOICED", "PAID", "CANCELLED",
    ]


def assert_blend_line(data: dict):
    _assert_common(data, "BlendLine")
    assert data["target_rate_lbs_per_acre"] > 0


def assert_blender(data: dict):
    _assert_common(data, "Blender")
    assert data["capacity_tons_per_hour"] > 0
    assert data["form_supported"] in ["DRY", "LIQUID", "BOTH"]
    assert data["status"] in ["ACTIVE", "OUT_OF_SERVICE"]


def assert_batch(data: dict):
    _assert_common(data, "BlendBatch")
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "VOIDED"]


def assert_truck(data: dict):
    _assert_common(data, "Truck")
    assert data["capacity_tons"] > 0
    assert data["status"] in ["ACTIVE", "OUT_OF_SERVICE"]


def assert_delivery_route(data: dict):
    _assert_common(data, "DeliveryRoute")
    assert data["status"] in ["PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED"]


def assert_delivery_stop(data: dict):
    _assert_common(data, "DeliveryStop")
    assert data["sequence"] >= 1
    assert data["status"] in ["PLANNED", "DELIVERED", "CANCELLED"]


def assert_ledger_entry(data: dict):
    """Append-only journal: carries id + created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "CreditLedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "CreditLedgerEntry.created_at must be ISO 8601"
    assert "version" not in data, "CreditLedgerEntry must not expose version (append-only)"
    assert "updated_at" not in data, "CreditLedgerEntry must not expose updated_at (append-only)"
    assert data["entry_type"] in [
        "PREPAY_FUNDED", "PREPAY_DRAWN", "PREPAY_FORFEITED", "PREPAY_REFUNDED",
        "INVOICE_POSTED", "PAYMENT_RECEIVED", "REBATE_CREDIT",
    ]
    assert isinstance(data["amount_cents"], int)


def assert_inventory_conservation(received: float, on_hand: float, shipped: float):
    """Physical tons conserved: received == on_hand + shipped (3-decimal tolerance)."""
    assert abs(received - (on_hand + shipped)) < 0.0005, (
        f"Conservation violated: received {received} != on_hand {on_hand} + shipped {shipped}"
    )
