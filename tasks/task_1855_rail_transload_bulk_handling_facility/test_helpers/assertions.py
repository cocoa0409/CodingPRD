"""Entity assertions and domain invariant checkers (PRD §2.4 common fields,
§3 per-entity field shapes)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer (PRD §2.4)"
    )


def _assert_lightweight(data: dict, entity: str):
    """SafetyIncident and SwitchOrder carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity}.updated_at must be absent (PRD §2.4)"
    assert "version" not in data, f"{entity}.version must be absent (PRD §2.4)"


def _assert_tonnage(value, field: str):
    assert isinstance(value, (int, float)), f"{field} must be numeric"


def assert_facility(data: dict):
    _assert_common(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["free_demurrage_hours"], int)
    assert isinstance(data["sit_free_days"], int)
    assert isinstance(data["switch_buffer_minutes"], int)
    assert isinstance(data["free_switches_per_period"], int)
    assert data["contamination_policy"] in ("STRICT_MATRIX", "WEIGHTED_SCORE")
    assert data["safety_posture"] in ("NORMAL", "ELEVATED", "SUSPENDED")
    assert isinstance(data["open_incident_count"], int)


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_standing"] in (
        "GOOD_STANDING", "CREDIT_WATCH", "CREDIT_HOLD",
    )
    assert data["demurrage_basis"] in ("CONSTRUCTIVE", "ACTUAL")
    assert data["sit_day_basis"] in ("CALENDAR", "BUSINESS")
    assert isinstance(data["allocated_car_spots"], int)


def assert_product(data: dict):
    _assert_common(data, "Product")
    assert isinstance(data["name"], str) and data["name"]
    assert data["hazard_class"] in ("NON_HAZARDOUS", "HAZARDOUS", "FOOD_GRADE")
    assert data["segregation_group"] in (
        "FERTILIZER", "FOOD_GRAIN", "CHEMICAL", "PETROLEUM",
    )
    assert isinstance(data["requires_full_clean"], bool)


def assert_track(data: dict):
    _assert_common(data, "Track")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["spot_capacity"], int) and data["spot_capacity"] > 0
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")
    assert data["derail_protection"] in ("ENGAGED", "DISENGAGED")
    assert isinstance(data["occupied_spots"], int)
    assert isinstance(data["reserved_spots"], int)


def assert_equipment(data: dict):
    _assert_common(data, "Equipment")
    assert isinstance(data["name"], str) and data["name"]
    assert data["equipment_type"] in ("CONVEYOR", "PUMP", "HOSE")
    assert data["status"] in ("AVAILABLE", "IN_USE", "CLEANING")
    assert "last_product_id" in data, "last_product_id must be present (nullable)"


def assert_safety_incident(data: dict):
    _assert_lightweight(data, "SafetyIncident")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str)
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_railcar(data: dict):
    _assert_common(data, "Railcar")
    assert isinstance(data["car_initials"], str) and data["car_initials"]
    assert isinstance(data["car_number"], str) and data["car_number"]
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["lot_id"], str)
    _assert_tonnage(data["quantity_loaded_tons"], "quantity_loaded_tons")
    _assert_tonnage(data["quantity_remaining_tons"], "quantity_remaining_tons")
    assert data["placement_status"] in (
        "REGISTERED", "ARRIVED", "SPOTTED", "IN_TRANSFER",
        "EMPTY_AWAITING_CLEANING", "CLEANING", "READY_FOR_RELEASE",
        "RELEASED", "DEPARTED",
    )
    assert data["hold_status"] in ("NONE", "SAFETY_HOLD")
    assert "track_id" in data, "track_id must be present (nullable until spotted)"
    assert "spot_number" in data, "spot_number must be present (nullable)"
    assert isinstance(data["demurrage_billable_days"], int)
    assert isinstance(data["demurrage_accrued_cents"], int)


def assert_inventory_lot(data: dict):
    _assert_common(data, "InventoryLot")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["status"] in ("ACTIVE", "CLOSED")
    _assert_tonnage(data["quantity_received_tons"], "quantity_received_tons")
    _assert_tonnage(data["quantity_shipped_tons"], "quantity_shipped_tons")
    _assert_tonnage(data["quantity_rejected_tons"], "quantity_rejected_tons")
    _assert_tonnage(data["quantity_on_hand_tons"], "quantity_on_hand_tons")
    assert isinstance(data["sit_free_days"], int)
    assert data["sit_day_basis"] in ("CALENDAR", "BUSINESS")
    assert isinstance(data["sit_daily_rate_cents"], int)
    assert isinstance(data["sit_billable_days"], int)
    assert isinstance(data["sit_accrued_cents"], int)
    assert "close_timestamp" in data, "close_timestamp must be present (nullable)"


def assert_spot_order(data: dict):
    _assert_common(data, "SpotOrder")
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["track_id"], str)
    assert isinstance(data["spot_number"], int)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "EXECUTED", "CLOSED", "CANCELLED", "SUPERSEDED",
    )
    assert "switch_order_id" in data, "switch_order_id must be present (nullable)"


def assert_switch_order(data: dict):
    _assert_lightweight(data, "SwitchOrder")
    assert isinstance(data["track_id"], str)
    assert data["move_type"] in ("SPOT", "PULL")
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["sequence_number"], int)
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_transfer_order(data: dict):
    _assert_common(data, "TransferOrder")
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["equipment_id"], str)
    _assert_tonnage(data["quantity_planned_tons"], "quantity_planned_tons")
    _assert_tonnage(data["quantity_completed_tons"], "quantity_completed_tons")
    assert isinstance(data["risk_score"], int)
    assert data["status"] in (
        "PLANNED", "ACTIVE", "PAUSED", "SUSPENDED", "COMPLETED", "CANCELLED",
    )


def assert_weight_ticket(data: dict):
    _assert_common(data, "WeightTicket")
    assert isinstance(data["transfer_order_id"], str)
    assert isinstance(data["railcar_id"], str)
    assert isinstance(data["truck_reference"], str)
    _assert_tonnage(data["gross_weight_tons"], "gross_weight_tons")
    _assert_tonnage(data["tare_weight_tons"], "tare_weight_tons")
    _assert_tonnage(data["truck_max_payload_tons"], "truck_max_payload_tons")
    _assert_tonnage(data["net_weight_tons"], "net_weight_tons")
    assert data["status"] in ("DRAFT", "CERTIFIED", "VOIDED")


def assert_charge_entry(data: dict):
    _assert_common(data, "ChargeEntry")
    assert isinstance(data["customer_id"], str)
    assert "railcar_id" in data, "railcar_id must be present (null for lot SIT)"
    assert "invoice_id" in data, "invoice_id must be present (null while accrued)"
    assert data["charge_type"] in (
        "DEMURRAGE", "SWITCHING", "CLEANING", "STORAGE_IN_TRANSIT",
    )
    _assert_tonnage(data["quantity"], "quantity")
    assert isinstance(data["unit_rate_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ACCRUED", "INVOICED", "VOIDED")


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["charge_count"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "DISPUTED")


def assert_lot_quantity_invariant(lot: dict):
    """PRD §3.2: quantity_on_hand_tons is always received minus shipped minus
    rejected."""
    on_hand = lot["quantity_on_hand_tons"]
    expected = (
        lot["quantity_received_tons"]
        - lot["quantity_shipped_tons"]
        - lot["quantity_rejected_tons"]
    )
    assert on_hand == expected, (
        f"lot on_hand {on_hand} != received-shipped-rejected {expected}"
    )
