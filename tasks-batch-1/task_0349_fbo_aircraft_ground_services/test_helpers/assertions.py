"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Every entity carries id/created_at/updated_at/version
per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and only increments"


def assert_operator(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["jeta_month_cumulative_gallons"], int)
    assert data["jeta_month_cumulative_gallons"] >= 0
    assert isinstance(data["open_invoice_balance_cents"], int)


def assert_aircraft(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["tail_number"], str) and len(data["tail_number"]) > 0
    assert data["fuel_type"] in ("JET_A", "AVGAS")
    assert isinstance(data["mtow_lb"], int) and data["mtow_lb"] >= 1
    assert data["weight_class"] in ("LIGHT", "MID", "HEAVY")


def assert_fuel_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert data["product"] in ("JET_A", "AVGAS")
    assert isinstance(data["base_price_cents_per_gal"], int) and data["base_price_cents_per_gal"] >= 1
    assert isinstance(data["tankering_fee_cents_per_gal"], int) and data["tankering_fee_cents_per_gal"] >= 0
    assert data["contract_status"] in ("ACTIVE", "EXPIRED")


def assert_service_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["aircraft_id"], str)
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert data["status"] in (
        "SCHEDULED", "ON_GROUND", "SERVICING", "READY_FOR_DEPARTURE", "DEPARTED", "CANCELLED"
    )
    assert isinstance(data["services_outstanding"], int) and data["services_outstanding"] >= 0


def assert_parking_spot(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["spot_type"] in ("HANGAR", "TIE_DOWN", "RAMP")
    assert data["max_weight_class"] in ("LIGHT", "MID", "HEAVY")
    assert data["spot_status"] in ("AVAILABLE", "OUT_OF_SERVICE")


def assert_parking_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["service_visit_id"], str)
    assert isinstance(data["spot_id"], str)
    assert data["status"] in ("HELD", "OCCUPIED", "RELEASED")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_fuel_order(data: dict):
    _assert_common(data)
    assert isinstance(data["service_visit_id"], str)
    assert isinstance(data["aircraft_id"], str)
    assert isinstance(data["fuel_contract_id"], str)
    assert data["product"] in ("JET_A", "AVGAS")
    assert isinstance(data["ordered_gallons"], int) and data["ordered_gallons"] >= 1
    assert isinstance(data["tankering"], bool)
    assert data["logistics_status"] in ("REQUESTED", "DISPATCHED", "FUELED", "CANCELLED")
    assert data["reconciliation_status"] in ("NOT_STARTED", "RECONCILED", "IN_REVIEW", "ADJUSTED")
    assert isinstance(data["priced_amount_cents"], int) and data["priced_amount_cents"] >= 0


def assert_into_plane_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["fuel_order_id"], str)
    assert isinstance(data["delivered_gallons"], int) and data["delivered_gallons"] >= 0
    assert isinstance(data["variance_gallons"], int)
    assert isinstance(data["variance_pct"], (int, float))
    assert data["outcome"] in ("RECONCILED", "FLAGGED")


def assert_ramp_service(data: dict):
    _assert_common(data)
    assert isinstance(data["service_visit_id"], str)
    assert data["service_type"] in ("LAVATORY", "GPU", "DE_ICE", "CREW_CAR", "CATERING")
    assert data["status"] in ("REQUESTED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0


def assert_ramp_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["service_visit_id"], str)
    assert isinstance(data["pad_id"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "REVOKED", "USED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["service_visit_id"], str)
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert data["status"] in ("ISSUED", "PAID", "PAST_DUE", "VOID")
