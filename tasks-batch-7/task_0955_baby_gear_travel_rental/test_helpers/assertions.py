"""Entity assertions and domain invariant checkers (PRD sections 2.4, 2.9, 3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["phone"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert isinstance(data["late_return_count"], int) and data["late_return_count"] >= 0
    assert (
        isinstance(data["captured_damage_count"], int)
        and data["captured_damage_count"] >= 0
    )


def assert_catalog_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("CRIB", "STROLLER", "CARSEAT")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert (
        isinstance(data["deposit_amount_cents"], int)
        and data["deposit_amount_cents"] > 0
    )
    assert isinstance(data["weight_kg"], (int, float)) and data["weight_kg"] > 0
    assert (
        isinstance(data["cleaning_turnaround_hours"], int)
        and data["cleaning_turnaround_hours"] >= 0
    )
    assert (
        isinstance(data["deep_clean_every_cycles"], int)
        and data["deep_clean_every_cycles"] >= 1
    )
    assert data["status"] in ("LISTED", "DELISTED")


def assert_inventory_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["condition_grade"] in ("A", "B", "C")
    assert data["status"] in (
        "AVAILABLE",
        "RESERVED",
        "RENTED_OUT",
        "AWAITING_CLEANING",
        "IN_CLEANING",
        "QUARANTINED",
        "RETIRED",
    )
    assert isinstance(data["cleans_since_deep"], int) and data["cleans_since_deep"] >= 0


def assert_hotel_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["commission_pct"], (int, float))
    assert 0 <= data["commission_pct"] <= 0.30
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_insurance_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["pricing_model"] in ("PER_DAY", "PERCENT_OF_RENTAL")
    assert isinstance(data["rate_value"], (int, float))
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert (
        isinstance(data["coverage_cap_cents"], int) and data["coverage_cap_cents"] > 0
    )
    assert isinstance(data["covered_severities"], list)
    for sev in data["covered_severities"]:
        assert sev in ("COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS")


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["delivery_address"], str)
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in (
        "QUOTED",
        "CONFIRMED",
        "DELIVERED",
        "RETURNED",
        "SETTLED",
        "CANCELLED",
    )
    assert data["payment_status"] in (
        "DEPOSIT_PENDING",
        "DEPOSIT_HELD",
        "SETTLED_PAID",
        "REFUNDED",
    )
    for money_field in (
        "quoted_total_cents",
        "gear_subtotal_cents",
        "deposit_hold_cents",
        "deposit_captured_cents",
        "deposit_released_cents",
        "late_fee_cents",
        "extension_charge_cents",
        "extension_days",
        "commission_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"{money_field} must be an integer"
        )
        assert data[money_field] >= 0, f"{money_field} must be non-negative"


def assert_reservation_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert data["status"] in (
        "PENDING",
        "ALLOCATED",
        "OUT",
        "RETURNED",
        "PENDING_REALLOCATION",
        "CANCELLED",
    )
    assert isinstance(data["unit_rate_cents"], int) and data["unit_rate_cents"] >= 0
    assert isinstance(data["line_charge_cents"], int) and data["line_charge_cents"] >= 0


def assert_delivery_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_date"], str)
    assert isinstance(data["zone_code"], str)
    assert (
        isinstance(data["vehicle_capacity_kg"], (int, float))
        and data["vehicle_capacity_kg"] > 0
    )
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED")
    assert (
        isinstance(data["planned_weight_kg"], (int, float))
        and data["planned_weight_kg"] >= 0
    )


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert data["stop_type"] in ("DELIVERY_SETUP", "PICKUP")
    assert isinstance(data["address"], str)
    assert isinstance(data["time_window_start"], str)
    assert isinstance(data["time_window_end"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "FAILED", "SKIPPED")
    assert isinstance(data["sequence"], int)


def assert_extension_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert isinstance(data["requested_end_date"], str)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "SUPERSEDED")
    assert (
        isinstance(data["extension_charge_cents"], int)
        and data["extension_charge_cents"] >= 0
    )


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reservation_line_id", ""))
    assert data["severity"] in ("COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS")
    assert (
        isinstance(data["repair_cost_cents"], int) and data["repair_cost_cents"] >= 0
    )
    assert isinstance(data["description"], str)
    assert data["status"] in (
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "DISPUTED",
        "CAPTURED",
    )
    assert (
        isinstance(data["capture_amount_cents"], int)
        and data["capture_amount_cents"] >= 0
    )


def assert_recall_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("catalog_item_id", ""))
    assert isinstance(data["recall_code"], str)
    assert data["severity"] in ("ADVISORY", "MANDATORY")
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")


def assert_cleaning_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["ticket_type"] in ("STANDARD", "DEEP", "RECALL_DECONTAMINATION")
    assert data["status"] in ("OPEN", "PASSED", "FAILED")


def assert_deposit_transaction(data: dict):
    """Append-only ledger entry: carries id and created_at only (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "ledger entries have no updated_at"
    assert "version" not in data, "ledger entries have no version"
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert data["txn_type"] in ("HOLD", "CAPTURE", "RELEASE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["reason"] in (
        "HOLD_AT_CONFIRM",
        "DAMAGE_CLAIM",
        "LATE_FEE",
        "CANCELLATION_FEE",
        "RELEASE_REMAINDER",
    )
    assert (
        isinstance(data["balance_after_cents"], int)
        and data["balance_after_cents"] >= 0
    )


def assert_deposit_conservation(reservation: dict):
    """Domain invariant (PRD 2.9): hold == captured + released."""
    hold = reservation["deposit_hold_cents"]
    captured = reservation["deposit_captured_cents"]
    released = reservation["deposit_released_cents"]
    assert hold == captured + released, (
        f"deposit ledger not conserved: hold {hold} != captured {captured} + released {released}"
    )
