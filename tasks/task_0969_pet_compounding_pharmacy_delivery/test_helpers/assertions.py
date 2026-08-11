"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-free UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """PRD §2.4: append-only records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-free UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_owner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_pet(data: dict):
    _assert_common_fields(data)
    assert data["species"] in ["DOG", "CAT", "BIRD", "REPTILE", "OTHER"]
    assert data["weight_kg"] > 0
    assert isinstance(data["allergies"], list)
    assert data["status"] in ["ALIVE", "DECEASED"]


def assert_veterinarian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in ["PENDING", "VERIFIED", "SUSPENDED", "REVOKED"]


def assert_drug_catalog_item(data: dict):
    _assert_common_fields(data)
    assert data["schedule"] in ["NON_CONTROLLED", "C_II", "C_III", "C_IV", "C_V"]
    assert isinstance(data["requires_cold_chain"], bool)
    assert data["unit_cost_cents"] >= 0
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_flavoring(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["allergen_tags"], list)
    assert data["surcharge_cents"] >= 0
    assert isinstance(data["compatible_species"], list)


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert data["dosage_form"] in ["SUSPENSION", "CAPSULE", "CHEW", "TOPICAL", "INJECTABLE"]
    assert data["strength_mg_per_ml"] > 0


def assert_prescription(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["RECEIVED", "VET_VERIFICATION_PENDING", "CLARIFICATION_REQUESTED",
                              "VERIFIED", "REJECTED", "EXPIRED", "EXHAUSTED"]
    assert isinstance(data["is_controlled"], bool)
    assert data["schedule_snapshot"] in ["NON_CONTROLLED", "C_II", "C_III", "C_IV", "C_V"]
    assert isinstance(data["refills_remaining"], int)
    assert isinstance(data["clarification_count"], int)


def assert_compound_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["CREATED", "ALLOCATED", "COMPOUNDING", "FLAVORING", "REWORK",
                              "QA_PENDING", "READY_TO_DISPATCH", "RECALL_HOLD", "DISPENSED",
                              "CANCELLED"]
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert isinstance(data["quantity_snapshot"], int)
    assert isinstance(data["provisional_price_cents"], int)
    assert isinstance(data["fill_number"], int)


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "QUARANTINED", "RECALLED", "EXPIRED", "EXHAUSTED"]
    for field in ("received_qty", "qty_on_hand", "qty_reserved", "qty_dispensed", "qty_wasted"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"


def assert_lot_allocation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["RESERVED", "CONSUMED", "RELEASED", "WASTED"]
    assert isinstance(data["qty_allocated"], int)


def assert_bench(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supports_controlled"], bool)
    assert data["status"] in ["ACTIVE", "MAINTENANCE"]


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert data["transit_status"] in ["LABEL_CREATED", "PICKED_UP", "IN_TRANSIT",
                                      "OUT_FOR_DELIVERY", "DELIVERED", "DELIVERY_EXCEPTION",
                                      "RETURNED_TO_PHARMACY", "QUARANTINED"]
    assert data["cold_chain_status"] in ["NOT_REQUIRED", "COMPLIANT", "EXCURSION_WATCH",
                                         "EXCURSION_BREACH"]
    assert isinstance(data["shipping_fee_cents"], int)
    assert isinstance(data["excursion_minutes_accumulated"], int)


def assert_temperature_reading(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["recorded_at"], str)
    assert isinstance(data["temp_celsius"], (int, float))


def assert_cooler(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "CONDITIONING", "RETIRED"]


def assert_wellness_plan(data: dict):
    _assert_common_fields(data)
    assert data["credit_value_cents"] > 0
    assert 0 <= data["discount_pct"] < 1
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CANCELLED"]
    assert isinstance(data["credits_remaining"], int)
    assert isinstance(data["credits_consumed"], int)


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "LAPSED"]
    assert 0 <= data["coverage_pct"] <= 1
    assert isinstance(data["deductible_met_cents"], int)
    assert isinstance(data["annual_used_cents"], int)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "APPEALED", "PAID"]
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["appeal_count"], int)


def assert_auto_ship_schedule(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]
    assert isinstance(data["interval_days"], int)
    assert isinstance(data["consecutive_failures"], int)


def assert_controlled_substance_entry(data: dict):
    _assert_append_only_fields(data)
    assert data["entry_type"] in ["RECEIVE", "DISPENSE", "WASTE", "RETURN", "ADJUST"]
    assert isinstance(data["qty_delta"], int)
    assert isinstance(data["running_balance"], int)
    assert data["running_balance"] >= 0


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert data["scope"] in ["LOT", "CATALOG_ITEM"]
    assert data["severity"] in ["CLASS_I", "CLASS_II", "CLASS_III"]
    assert data["status"] in ["DRAFT", "ACTIVE", "COMPLETED"]


def assert_recall_task(data: dict):
    _assert_common_fields(data)
    assert data["channel"] in ["EMAIL", "PHONE"]
    assert data["status"] in ["PENDING", "NOTIFIED", "ACKNOWLEDGED", "FAILED"]


def assert_lot_quantities(lot: dict, on_hand: int, reserved: int, dispensed: int, wasted: int):
    """Lot quantity counters must match the expected four-tuple exactly."""
    assert lot["qty_on_hand"] == on_hand, f"qty_on_hand expected {on_hand}, got {lot['qty_on_hand']}"
    assert lot["qty_reserved"] == reserved, f"qty_reserved expected {reserved}, got {lot['qty_reserved']}"
    assert lot["qty_dispensed"] == dispensed, f"qty_dispensed expected {dispensed}, got {lot['qty_dispensed']}"
    assert lot["qty_wasted"] == wasted, f"qty_wasted expected {wasted}, got {lot['qty_wasted']}"
