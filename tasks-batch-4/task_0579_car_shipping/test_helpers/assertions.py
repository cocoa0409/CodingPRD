"""Entity assertions and domain invariant checkers for the Car Shipping API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_CARRIER_STATES = {"ACTIVE", "SUSPENDED"}
_ORDER_STATES = {
    "DRAFT", "QUOTED", "LISTED", "DISPATCHED", "PICKED_UP", "DELIVERED", "CLOSED", "CANCELLED",
}
_QUOTE_STATES = {"OFFERED", "ACCEPTED", "SUPERSEDED"}
_LISTING_STATES = {"OPEN", "AWARDED", "WITHDRAWN"}
_OFFER_STATES = {"PENDING", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN"}
_ASSIGNMENT_STATES = {"DISPATCHED", "REVOKED", "COMPLETED"}
_CLAIM_STATES = {"SUBMITTED", "RETURNED_FOR_INFO", "APPROVED", "DENIED", "PAID"}
_LEDGER_KINDS = {"DEPOSIT", "COD_PAYMENT", "REFUND", "CLAIM_PAYOUT"}
_LEDGER_STATES = {"POSTED", "VOIDED"}
_TRANSPORT = {"OPEN", "ENCLOSED"}
_DELIVERY_MODE = {"DOOR_TO_DOOR", "TERMINAL"}
_SERVICE_LEVEL = {"STANDARD", "EXPEDITED"}
_PHASES = {"PICKUP", "DELIVERY"}


def _assert_common_fields(data: dict, label: str) -> None:
    """id + created_at + updated_at + version (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_shipper(data: dict) -> None:
    _assert_common_fields(data, "Shipper")
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0


def assert_terminal(data: dict) -> None:
    _assert_common_fields(data, "Terminal")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("dock_zip"), str)
    assert isinstance(data.get("dock_count"), int) and data["dock_count"] >= 1
    assert isinstance(data.get("buffer_minutes"), int) and data["buffer_minutes"] >= 0


def assert_carrier(data: dict) -> None:
    _assert_common_fields(data, "Carrier")
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert isinstance(data.get("mc_number"), str) and len(data["mc_number"]) > 0
    assert isinstance(data.get("cargo_insurance_limit_cents"), int)
    assert is_iso8601_timestamp(data.get("insurance_expiry_date", ""))
    assert data.get("equipment_type") in _TRANSPORT
    assert isinstance(data.get("rating"), (int, float))
    assert isinstance(data.get("aggregate_exposure_cents"), int)
    assert data["aggregate_exposure_cents"] >= 0
    assert data.get("status") in _CARRIER_STATES


def assert_shipment_order(data: dict) -> None:
    _assert_common_fields(data, "ShipmentOrder")
    assert isinstance(data.get("shipper_id"), str) and len(data["shipper_id"]) > 0
    assert isinstance(data.get("route_miles"), int) and data["route_miles"] > 0
    assert data.get("transport_type") in _TRANSPORT
    assert data.get("delivery_mode") in _DELIVERY_MODE
    assert data.get("service_level") in _SERVICE_LEVEL
    assert data.get("status") in _ORDER_STATES
    assert isinstance(data.get("amount_paid_cents"), int)
    assert isinstance(data.get("has_open_claim"), bool)


def assert_vehicle(data: dict) -> None:
    _assert_common_fields(data, "Vehicle")
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert isinstance(data.get("make"), str)
    assert isinstance(data.get("model"), str)
    assert isinstance(data.get("year"), int)
    assert isinstance(data.get("is_inoperable"), bool)
    assert isinstance(data.get("declared_value_cents"), int)


def assert_quote(data: dict) -> None:
    _assert_common_fields(data, "Quote")
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert isinstance(data.get("base_cents"), int)
    assert isinstance(data.get("transport_surcharge_cents"), int)
    assert isinstance(data.get("inoperable_surcharge_cents"), int)
    assert isinstance(data.get("multi_car_discount_cents"), int)
    assert isinstance(data.get("total_cents"), int)
    assert is_iso8601_timestamp(data.get("valid_until", ""))
    assert data.get("status") in _QUOTE_STATES


def assert_load_listing(data: dict) -> None:
    _assert_common_fields(data, "LoadListing")
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert isinstance(data.get("offered_carrier_pay_cents"), int)
    assert isinstance(data.get("expedited"), bool)
    assert data.get("status") in _LISTING_STATES


def assert_dispatch_offer(data: dict) -> None:
    _assert_common_fields(data, "DispatchOffer")
    assert isinstance(data.get("listing_id"), str) and len(data["listing_id"]) > 0
    assert isinstance(data.get("carrier_id"), str) and len(data["carrier_id"]) > 0
    assert isinstance(data.get("ask_pay_cents"), int)
    assert is_iso8601_timestamp(data.get("pickup_eta", ""))
    assert isinstance(data.get("round_no"), int) and data["round_no"] >= 1
    assert data.get("status") in _OFFER_STATES


def assert_assignment(data: dict) -> None:
    _assert_common_fields(data, "Assignment")
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert isinstance(data.get("carrier_id"), str) and len(data["carrier_id"]) > 0
    assert isinstance(data.get("offer_id"), str) and len(data["offer_id"]) > 0
    assert isinstance(data.get("carrier_pay_cents"), int)
    assert data.get("status") in _ASSIGNMENT_STATES


def assert_inspection(data: dict) -> None:
    _assert_common_fields(data, "Inspection")
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert data.get("phase") in _PHASES
    assert isinstance(data.get("damage_count"), int) and data["damage_count"] >= 0
    assert isinstance(data.get("observed_inoperable_count"), int)
    assert data["observed_inoperable_count"] >= 0
    assert isinstance(data.get("odometer"), int)


def assert_claim(data: dict) -> None:
    _assert_common_fields(data, "Claim")
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert isinstance(data.get("claimed_cents"), int)
    assert data.get("status") in _CLAIM_STATES


def assert_ledger_entry(data: dict) -> None:
    """LedgerEntry is append-only: only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "LedgerEntry.created_at must be ISO 8601"
    assert isinstance(data.get("order_id"), str) and len(data["order_id"]) > 0
    assert data.get("kind") in _LEDGER_KINDS
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in _LEDGER_STATES


def assert_deposit_split_invariant(order: dict) -> None:
    """deposit_cents + cod_balance_cents == quoted_total_cents exactly (PRD §3.3)."""
    assert order.get("deposit_cents") is not None
    assert order.get("cod_balance_cents") is not None
    assert order.get("quoted_total_cents") is not None
    assert order["deposit_cents"] + order["cod_balance_cents"] == order["quoted_total_cents"], (
        "deposit_cents + cod_balance_cents must equal quoted_total_cents exactly"
    )
