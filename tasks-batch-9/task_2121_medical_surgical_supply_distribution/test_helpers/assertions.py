"""Entity assertions and domain invariant checkers."""

import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ClaimStatus,
    ContractLineActivationState,
    ControlledLicenseStatus,
    FormularyStatus,
    FulfillmentStatus,
    GpoContractStatus,
    GpoMemberClass,
    HandlingClass,
    ItemStatus,
    LineStatus,
    LotStatus,
    RecallClass,
    RecallStatus,
    RoomType,
    RouteStatus,
    SettlementStatus,
    SubstitutionStatus,
    Uom,
    VehicleClass,
)

# PRD section 2.4: timestamps are ISO 8601 UTC with three fractional digits.
_MILLIS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# ─── Generic structural helpers ───────────────────────────────────────────

def assert_millisecond_timestamp(value: str, field: str = "timestamp") -> None:
    """PRD section 2.4 requires three fractional digits on API timestamps."""
    assert isinstance(value, str) and _MILLIS_TIMESTAMP_RE.match(value), (
        f"{field} must be an ISO 8601 UTC timestamp with exactly three "
        f"fractional digits, got {value!r}"
    )


def assert_common_fields(data: dict, entity_name: str) -> None:
    """id / created_at / updated_at / version, per PRD section 2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a bare UUID with no type prefix, "
        f"got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer beginning at 1, "
        f"got {data.get('version')!r}"
    )


def assert_instant_equals(actual: str, expected_prefix: str, field: str) -> None:
    """Compare a server timestamp against a logical-clock instant.

    `expected_prefix` is the second-precision instant, e.g. 2026-08-01T00:00:00.
    """
    assert isinstance(actual, str), f"{field} must be a timestamp string, got {actual!r}"
    normalised = actual.replace("Z", "")
    assert normalised.startswith(expected_prefix), (
        f"{field} should read the logical clock at {expected_prefix}Z, got {actual!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_supply_room(data: dict) -> None:
    assert_common_fields(data, "SupplyRoom")
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert isinstance(data["room_code"], str) and 1 <= len(data["room_code"]) <= 40
    assert data["gpo_member_class"] in _values(GpoMemberClass)
    assert data["room_type"] in _values(RoomType)
    assert isinstance(data["refrigerated"], bool)
    assert isinstance(data["controlled_secured"], bool)
    assert data["controlled_license_status"] in _values(ControlledLicenseStatus)
    assert isinstance(data["window_open_min"], int)
    assert isinstance(data["window_close_min"], int)
    assert 0 <= data["window_open_min"] < data["window_close_min"] <= 1439
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["open_commitment_cents"], int)
    assert data["open_commitment_cents"] >= 0, (
        "open_commitment_cents is a running ledger and may never fall below zero"
    )


def assert_item(data: dict) -> None:
    assert_common_fields(data, "Item")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["description"], str)
    assert isinstance(data["manufacturer_code"], str) and data["manufacturer_code"]
    assert data["uom"] in _values(Uom)
    assert isinstance(data["units_per_parent"], int) and data["units_per_parent"] >= 1
    assert data["handling_class"] in _values(HandlingClass)
    assert isinstance(data["wac_cents"], int) and data["wac_cents"] > 0
    assert isinstance(data["is_lot_tracked"], bool)
    assert data["status"] in _values(ItemStatus)


def assert_gpo_contract(data: dict) -> None:
    assert_common_fields(data, "GpoContract")
    assert isinstance(data["manufacturer_code"], str) and data["manufacturer_code"]
    assert isinstance(data["contract_code"], str) and data["contract_code"]
    assert data["tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["member_class_scope"] in _values(GpoMemberClass)
    assert isinstance(data["committed_volume_units"], int)
    assert data["committed_volume_units"] >= 0
    assert isinstance(data["effective_from"], str) and data["effective_from"]
    assert isinstance(data["effective_to"], str) and data["effective_to"]
    assert data["status"] in _values(GpoContractStatus)
    assert isinstance(data["chargeback_payable_cents"], int)


def assert_contract_line(data: dict) -> None:
    assert_common_fields(data, "ContractLine")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["tier_price_cents"], int) and data["tier_price_cents"] > 0
    assert isinstance(data["floor_price_cents"], int) and data["floor_price_cents"] > 0
    assert isinstance(data["chargeback_eligible"], bool)
    assert data["activation_state"] in _values(ContractLineActivationState)


def assert_formulary_item(data: dict) -> None:
    assert_common_fields(data, "FormularyItem")
    assert is_valid_uuid(data["supply_room_id"])
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["facility_item_code"], str) and data["facility_item_code"]
    assert data["formulary_status"] in _values(FormularyStatus)
    assert isinstance(data["par_qty"], int) and data["par_qty"] > 0
    assert isinstance(data["reorder_point"], int)
    assert 0 <= data["reorder_point"] < data["par_qty"]
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0, (
        "on_hand_qty is floored at zero"
    )
    assert isinstance(data["lum_enabled"], bool)


def assert_lot(data: dict) -> None:
    assert_common_fields(data, "Lot")
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["expiry_date"], str) and data["expiry_date"]
    assert isinstance(data["received_quantity"], int) and data["received_quantity"] > 0
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert data["status"] in _values(LotStatus)


def assert_replenishment_order(data: dict) -> None:
    assert_common_fields(data, "ReplenishmentOrder")
    assert is_valid_uuid(data["supply_room_id"])
    assert data["fulfillment_status"] in _values(FulfillmentStatus)
    assert data["settlement_status"] in _values(SettlementStatus)
    assert isinstance(data["order_total_cents"], int)
    assert data["order_total_cents"] >= 0


def assert_order_line(data: dict) -> None:
    assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["requested_qty"], int) and data["requested_qty"] > 0
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] >= 0
    assert isinstance(data["pinned_unit_price_cents"], int)
    assert isinstance(data["extended_price_cents"], int)
    assert isinstance(data["line_fee_cents"], int)
    assert isinstance(data["chargeback_eligible"], bool)
    assert data["line_status"] in _values(LineStatus)


def assert_substitution_request(data: dict) -> None:
    assert_common_fields(data, "SubstitutionRequest")
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["proposed_item_id"])
    assert isinstance(data["requested_by_user_id"], str)
    assert data["requested_by_user_id"]
    assert isinstance(data["justification"], str)
    assert isinstance(data["rounds_used"], int) and data["rounds_used"] >= 0
    assert data["status"] in _values(SubstitutionStatus)


def assert_recall_notice(data: dict) -> None:
    assert_common_fields(data, "RecallNotice")
    assert is_valid_uuid(data["item_id"])
    assert data["recall_class"] in _values(RecallClass)
    assert isinstance(data["reason"], str)
    assert data["status"] in _values(RecallStatus)
    assert isinstance(data["quarantined_lot_count"], int)
    assert data["quarantined_lot_count"] >= 0
    assert isinstance(data["backordered_line_count"], int)
    assert data["backordered_line_count"] >= 0


def assert_delivery_route(data: dict) -> None:
    assert_common_fields(data, "DeliveryRoute")
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["service_date"], str)
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["service_date"]), (
        f"service_date must be YYYY-MM-DD, got {data['service_date']!r}"
    )
    assert data["vehicle_class"] in _values(VehicleClass)
    assert isinstance(data["planned_order_count"], int)
    assert data["planned_order_count"] >= 0
    assert isinstance(data["cold_units_loaded"], int) and data["cold_units_loaded"] >= 0
    assert data["status"] in _values(RouteStatus)


def assert_chargeback_claim(data: dict) -> None:
    assert_common_fields(data, "ChargebackClaim")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["submitted_by_user_id"], str)
    assert data["submitted_by_user_id"]
    assert isinstance(data["gross_chargeback_cents"], int)
    assert data["gross_chargeback_cents"] >= 0
    assert isinstance(data["admin_fee_pct"], (int, float))
    assert isinstance(data["admin_fee_cents"], int) and data["admin_fee_cents"] >= 0
    assert isinstance(data["net_chargeback_cents"], int)
    assert isinstance(data["eligible_line_count"], int)
    assert data["eligible_line_count"] >= 0
    assert data["status"] in _values(ClaimStatus)


def assert_replenishment_suggestion(data: dict) -> None:
    """The computed projection returned by the replenishment-suggestion read."""
    assert isinstance(data["eligible"], bool)
    assert isinstance(data["deficit_eaches"], int) and data["deficit_eaches"] >= 0
    assert isinstance(data["suggested_case_qty"], int)
    assert data["suggested_case_qty"] >= 0
    assert isinstance(data["suggested_each_qty"], int)
    assert data["suggested_each_qty"] >= 0
    assert isinstance(data["suggested_total_eaches"], int)
    assert data["suggested_total_eaches"] >= 0
    assert data["variant"] in ("STANDARD_TOPOFF", "LUM_SPLIT")


# ─── Domain invariants ────────────────────────────────────────────────────

def assert_lot_units_conserved(lot: dict, allocated_lines: list) -> None:
    """PRD section 3.5: quantity_on_hand plus the quantity currently allocated
    out of the lot must equal received_quantity."""
    allocated = sum(line["allocated_qty"] for line in allocated_lines)
    assert lot["quantity_on_hand"] + allocated == lot["received_quantity"], (
        f"Lot units not conserved: quantity_on_hand {lot['quantity_on_hand']} + "
        f"allocated {allocated} != received_quantity {lot['received_quantity']}"
    )


def assert_contract_ledger_matches_claims(contract: dict, claims: list) -> None:
    """PRD section 2.10: chargeback_payable_cents is the sum of
    net_chargeback_cents over claims whose status is SUBMITTED, ACCEPTED or
    RECONCILED."""
    payable_states = ("SUBMITTED", "ACCEPTED", "RECONCILED")
    expected = sum(
        claim["net_chargeback_cents"]
        for claim in claims
        if claim["status"] in payable_states
    )
    assert contract["chargeback_payable_cents"] == expected, (
        f"chargeback_payable_cents {contract['chargeback_payable_cents']} does not "
        f"equal the sum {expected} of net_chargeback_cents over claims in "
        f"{payable_states}"
    )


def assert_room_commitment_matches_open_orders(room: dict, orders: list) -> None:
    """PRD section 2.10: open_commitment_cents is the sum of order_total_cents
    over the room's orders whose fulfillment_status is SUBMITTED, ALLOCATED,
    IN_TRANSIT or HELD."""
    open_states = ("SUBMITTED", "ALLOCATED", "IN_TRANSIT", "HELD")
    expected = sum(
        order["order_total_cents"]
        for order in orders
        if order["fulfillment_status"] in open_states
    )
    assert room["open_commitment_cents"] == expected, (
        f"open_commitment_cents {room['open_commitment_cents']} does not equal "
        f"the sum {expected} of order_total_cents over orders in {open_states}"
    )
