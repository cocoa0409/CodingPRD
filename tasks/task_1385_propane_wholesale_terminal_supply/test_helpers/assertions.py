"""Entity assertions and domain invariant checkers.

Common-field discipline follows the PRD: primary resources carry id,
created_at, updated_at, version; PriceIndexPublication is the one append-only
exception and must NOT expose updated_at or version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an int starting at 1"


def assert_terminal(data: dict):
    _assert_common_fields(data, "Terminal")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["storage_capacity_gal"], int)
    assert isinstance(data["reserve_floor_gal"], int)
    assert isinstance(data["winter_reserve_floor_gal"], int)
    assert isinstance(data["rack_bay_count"], int)
    assert isinstance(data["on_hand_gal"], int)
    assert data["allocation_posture"] in ["NORMAL", "CURTAILED"]
    assert isinstance(data["ops_epoch"], int)


def assert_inventory_summary(data: dict):
    assert isinstance(data["on_hand_gal"], int)
    assert isinstance(data["reserved_gal"], int)
    assert isinstance(data["effective_reserve_floor_gal"], int)
    assert isinstance(data["available_to_promise_gal"], int)
    assert data["season_posture"] in ["SUMMER_BUILD", "WINTER_DRAW"]
    assert data["allocation_posture"] in ["NORMAL", "CURTAILED"]
    assert isinstance(data["open_request_gal"], int)


def assert_supply_contract(data: dict):
    _assert_common_fields(data, "SupplyContract")
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["contracted_volume_gal"], int)
    assert isinstance(data["delivered_volume_gal"], int)
    assert isinstance(data["receipt_window_start"], str)
    assert isinstance(data["receipt_window_end"], str)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED",
    ]


def assert_rail_shipment(data: dict):
    _assert_common_fields(data, "RailShipment")
    assert is_valid_uuid(data.get("supply_contract_id", ""))
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert isinstance(data["volume_gal"], int)
    assert isinstance(data["railcar_count"], int)
    assert isinstance(data["scheduled_arrival_date"], str)
    assert data["status"] in [
        "TENDERED", "IN_TRANSIT", "ARRIVED", "UNLOADED", "CANCELLED",
    ]
    assert "unloaded_at" in data


def assert_dealer(data: dict):
    _assert_common_fields(data, "Dealer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["fee_balance_cents"], int)
    assert isinstance(data["ledger_exposure_cents"], int)
    assert isinstance(data["committed_exposure_cents"], int)
    assert data["credit_status"] in ["GOOD_STANDING", "WATCH", "SUSPENDED"]


def assert_dealer_contract(data: dict):
    _assert_common_fields(data, "DealerContract")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert data["pricing_mode"] in ["INDEX", "FIXED"]
    if data["pricing_mode"] == "FIXED":
        assert isinstance(data["fixed_price_mc_per_gal"], int)
    assert isinstance(data["volume_committed_gal"], int)
    assert isinstance(data["volume_drawn_gal"], int)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED", "CANCELLED",
    ]


def assert_price_index_publication(data: dict):
    """Append-only configuration: id + created_at; never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), \
        "PriceIndexPublication.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "PriceIndexPublication.created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "append-only publication must not carry updated_at"
    assert "version" not in data, \
        "append-only publication must not carry version"
    assert data["index_name"] in ["MT_BELVIEU", "CONWAY"]
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["price_mc_per_gal"], int)


def assert_freight_zone(data: dict):
    _assert_common_fields(data, "FreightZone")
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["one_way_drive_minutes"], int)
    assert isinstance(data["freight_mc_per_gal"], int)
    assert isinstance(data["min_freight_cents"], int)


def assert_truck(data: dict):
    _assert_common_fields(data, "TransportTruck")
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["capacity_gal"], int)
    assert isinstance(data["weekly_hours_limit_minutes"], int)
    assert data["status"] in ["AVAILABLE", "OUT_OF_SERVICE"]
    assert isinstance(data["weekly_committed_minutes"], int)


def assert_delivery_order(data: dict):
    _assert_common_fields(data, "DeliveryOrder")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert is_valid_uuid(data.get("freight_zone_id", ""))
    assert isinstance(data["requested_gal"], int)
    assert data["fulfillment_status"] in [
        "REQUESTED", "ALLOCATED", "SHORTED", "SCHEDULED", "LOADED",
        "DELIVERED", "CANCELLED",
    ]
    assert data["invoice_status"] in ["NOT_READY", "OPEN", "PAID", "VOID"]
    assert data["pricing_mode"] in ["FIXED", "INDEX", "SPOT"]
    # Nullable-until-milestone fields: key present, value int/str or None.
    for key in ("allocated_gal", "truck_id", "provisional_total_cents",
                "final_total_cents", "open_balance_cents",
                "planned_load_start", "planned_load_end",
                "est_trip_minutes", "invoiced_at"):
        assert key in data, f"DeliveryOrder.{key} must be present (may be null)"


def assert_cold_snap_event(data: dict):
    _assert_common_fields(data, "ColdSnapEvent")
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert data["severity"] in ["WATCH", "WARNING", "EMERGENCY"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ["DECLARED", "ACTIVE", "LIFTED"]


def assert_allocation_run(data: dict):
    _assert_common_fields(data, "AllocationRun")
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert isinstance(data["run_index"], int)
    assert data["status"] in ["OPEN", "COMPUTED", "RATIFIED", "SUPERSEDED"]
    assert "pool_gal" in data
    assert isinstance(data["results"], list)
    for row in data["results"]:
        assert is_valid_uuid(row.get("order_id", "")), \
            "AllocationRun.results[].order_id must be a UUID"
        assert isinstance(row["allocated_gal"], int)
        assert row["outcome"] in ["ALLOCATED", "SHORTED"]


def assert_dealer_payment(data: dict):
    _assert_common_fields(data, "DealerPayment")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in ["ACH", "CHECK", "WIRE"]
    assert data["status"] in ["POSTED", "RETURNED"]
    assert isinstance(data["applications"], list)
    for row in data["applications"]:
        assert is_valid_uuid(row.get("order_id", "")), \
            "DealerPayment.applications[].order_id must be a UUID"
        assert isinstance(row["amount_cents"], int)
