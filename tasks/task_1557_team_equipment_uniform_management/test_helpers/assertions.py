"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every resource carries the four
system-managed fields (PRD section on common resource properties).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_player(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["position_group"] in ("OFFENSE", "DEFENSE", "SPECIAL_TEAMS")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RELEASED")


def assert_inventory_pool(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert data["garment_type"] in ("GAME_JERSEY", "GAME_PANTS", "PRACTICE_JERSEY",
                                    "PRACTICE_PANTS", "SOCKS")
    assert isinstance(data["size_code"], str) and data["size_code"]
    for field in ("stock_on_hand", "reserved_quantity", "in_laundry_quantity",
                  "available_quantity", "reorder_point", "reorder_batch_size"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["reorder_blocked"], bool)
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_pool_conservation(data: dict):
    """The PRD availability-ledger invariant: stock on hand always equals
    available plus reserved plus in-laundry."""
    assert data["stock_on_hand"] == (
        data["available_quantity"] + data["reserved_quantity"]
        + data["in_laundry_quantity"]
    ), (
        f"Pool conservation broken: stock_on_hand {data['stock_on_hand']} != "
        f"available {data['available_quantity']} + reserved {data['reserved_quantity']} "
        f"+ in_laundry {data['in_laundry_quantity']}"
    )


def assert_supplier_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert isinstance(data["start_on"], str)
    assert isinstance(data["end_on"], str)
    assert isinstance(data["allocation_caps"], list)
    assert isinstance(data["units_committed"], list)
    assert isinstance(data["default_lead_time_days"], int)


def committed_units_for(contract: dict, garment_type: str) -> int:
    """Read the derived committed-units entry for one garment type."""
    for entry in contract.get("units_committed", []):
        if entry.get("garment_type") == garment_type:
            return entry.get("committed_units", 0)
    return 0


def cap_for(contract: dict, garment_type: str) -> int:
    for entry in contract.get("allocation_caps", []):
        if entry.get("garment_type") == garment_type:
            return entry.get("max_units", 0)
    return 0


def assert_kit_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier_contract_id"], str)
    assert data["source"] in ("MANUAL", "AUTO_REORDER")
    assert data["status"] in ("SUBMITTED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED")
    assert isinstance(data["lines"], list) and data["lines"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_kit_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["player_id"], str)
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert isinstance(data["jersey_number"], int) and 0 <= data["jersey_number"] <= 99
    assert isinstance(data["jersey_pool_id"], str)
    assert isinstance(data["pants_pool_id"], str)
    assert data["status"] in ("RESERVED", "ISSUED", "RETURNED", "RELEASED", "LOST")


def assert_gear_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["item_type"] in ("HELMET", "SHOULDER_PADS", "GIRDLE_PADS", "KNEE_BRACE")
    assert isinstance(data["size_spec"], str)
    assert data["condition_grade"] in ("A", "B", "C", "F")
    assert isinstance(data["acquired_on"], str)
    assert data["status"] in ("IN_STOCK", "ISSUED", "OUT_FOR_RECONDITIONING", "RETIRED")


def assert_reconditioning_job(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert isinstance(data["sent_on"], str)
    assert isinstance(data["due_back_on"], str)
    assert data["status"] in ("OUT", "PASSED", "FAILED")


def assert_game_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert isinstance(data["opponent_name"], str)
    assert isinstance(data["kickoff_at"], str)
    assert data["designated_kit"] in ("HOME", "AWAY", "ALTERNATE")
    assert data["status"] in ("SCHEDULED", "KIT_LOCKED", "COMPLETED", "CANCELLED")
    assert data["laundry_status"] in ("NOT_STARTED", "COLLECTING", "IN_WASH",
                                      "READY", "CLOSED")


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["player_id"], str)
    assert data["claim_type"] in ("LOST", "DAMAGED")
    assert isinstance(data["base_value_cents"], int) and data["base_value_cents"] > 0
    assert data["status"] in ("REPORTED", "ASSESSED", "SETTLED", "WAIVED")
    assert isinstance(data["provisional_fee_cents"], int)


def assert_disposition_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert data["garment_type"] in ("GAME_JERSEY", "GAME_PANTS", "PRACTICE_JERSEY",
                                    "PRACTICE_PANTS", "SOCKS")
    assert data["method"] in ("RETURN_TO_STOCK", "DONATE", "MEMORABILIA_SALE", "DISCARD")
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED", "EXECUTED")
