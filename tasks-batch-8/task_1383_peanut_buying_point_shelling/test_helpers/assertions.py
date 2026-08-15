"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_buying_point(data: dict):
    _assert_common_fields(data, "BuyingPoint")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["drying_rate_per_cycle_cents"], int)
    assert isinstance(data["quota_price_cents_per_ton"], int)
    assert isinstance(data["additional_price_cents_per_ton"], int)
    assert isinstance(data["loan_rate_quota_cents_per_ton"], int)
    assert isinstance(data["loan_rate_additional_cents_per_ton"], int)
    assert data["intake_posture"] in ["OPEN", "RESTRICTED", "SUSPENDED"]
    assert isinstance(data["ops_run_index"], int)


def assert_grower(data: dict):
    _assert_common_fields(data, "Grower")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["farm_number"], str) and data["farm_number"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["no_show_strikes"], int)


def assert_discount_schedule(data: dict):
    _assert_common_fields(data, "DiscountSchedule")
    assert isinstance(data["schedule_code"], str) and data["schedule_code"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["moisture_tiers"], list)
    assert isinstance(data["foreign_material_tiers"], list)
    assert isinstance(data["damage_rate_cents_per_pct"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_load(data: dict):
    _assert_common_fields(data, "FarmerStockLoad")
    assert isinstance(data["grower_id"], str)
    assert isinstance(data["crop_year"], int)
    assert data["status"] in [
        "REPORTED", "WEIGHED", "GRADED", "STORED", "DEPLETED", "REJECTED",
    ]
    assert data["aflatoxin_status"] in [
        "UNTESTED", "SAMPLED", "PASSED", "SEGREGATED", "REJECTED",
    ]
    assert data["drying_status"] in [
        "NOT_REQUIRED", "REQUIRED", "BOOKED", "DRIED",
    ]


def assert_grade_sheet(data: dict):
    _assert_common_fields(data, "GradeSheet")
    assert isinstance(data["load_id"], str)
    assert isinstance(data["inspector_ref"], str)
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["foreign_material_pct"], (int, float))
    assert isinstance(data["damage_pct"], (int, float))
    assert isinstance(data["lsk_pct"], (int, float))
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]


def assert_aflatoxin_certificate(data: dict):
    _assert_common_fields(data, "AflatoxinCertificate")
    assert isinstance(data["load_id"], str)
    assert isinstance(data["sample_ref"], str)
    assert isinstance(data["lab_tech_ref"], str)
    assert isinstance(data["retest_count"], int)
    assert data["status"] in ["SAMPLED", "RESULT_RECORDED", "CONFIRMED"]


def assert_dryer(data: dict):
    _assert_common_fields(data, "Dryer")
    assert isinstance(data["buying_point_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["cycle_capacity_tons"], int)
    assert isinstance(data["cycle_hours"], int)


def assert_dryer_booking(data: dict):
    _assert_common_fields(data, "DryerBooking")
    assert isinstance(data["dryer_id"], str)
    assert isinstance(data["load_id"], str)
    assert isinstance(data["tons"], (int, float))
    assert is_iso8601_timestamp(data["starts_at"])
    assert isinstance(data.get("ends_at"), str)
    assert data["status"] in ["BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_warehouse(data: dict):
    _assert_common_fields(data, "Warehouse")
    assert isinstance(data["buying_point_id"], str)
    assert isinstance(data["name"], str)
    assert data["compartment"] in ["GENERAL", "SEGREGATED"]
    assert isinstance(data["capacity_tons"], int)
    assert isinstance(data["stored_tons"], (int, float))
    assert isinstance(data["reserved_tons"], (int, float))
    assert isinstance(data["free_tons"], (int, float))


def assert_warehouse_partition(data: dict):
    """Partition invariant: stored + reserved + free == capacity (PRD §2.7)."""
    total = data["stored_tons"] + data["reserved_tons"] + data["free_tons"]
    assert abs(total - data["capacity_tons"]) < 1e-6, (
        f"warehouse partition drifted: {data['stored_tons']} + "
        f"{data['reserved_tons']} + {data['free_tons']} != {data['capacity_tons']}"
    )


def assert_storage_receipt(data: dict):
    _assert_common_fields(data, "StorageReceipt")
    assert isinstance(data["warehouse_id"], str)
    assert isinstance(data["load_id"], str)
    assert isinstance(data["segregated"], bool)
    assert isinstance(data["tons_initial"], (int, float))
    assert isinstance(data["tons_remaining"], (int, float))
    assert data["status"] in ["OPEN", "PLEDGED", "CLOSED", "FORFEITED", "CANCELLED"]


def assert_loan_pledge(data: dict):
    _assert_common_fields(data, "LoanPledge")
    assert isinstance(data["grower_id"], str)
    assert isinstance(data["storage_receipt_id"], str)
    assert isinstance(data["pledged_tons"], (int, float))
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)
    assert data["margin_status"] in ["MARGIN_OK", "MARGIN_CALL"]
    assert data["status"] in ["ACTIVE", "REPAID", "FORECLOSED"]


def assert_sheller_contract(data: dict):
    _assert_common_fields(data, "ShellerContract")
    assert isinstance(data["buying_point_id"], str)
    assert isinstance(data["sheller_ref"], str)
    assert isinstance(data["total_units_tons"], (int, float))
    assert isinstance(data["price_per_ton_cents"], int)
    assert isinstance(data["accepts_segregated"], bool)
    assert isinstance(data["default_count"], int)
    assert data["status"] in [
        "DRAFT", "ACTIVE", "FULFILLED", "DEFAULTED", "CANCELLED",
    ]


def assert_delivery_call(data: dict):
    _assert_common_fields(data, "DeliveryCall")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["requested_tons"], (int, float))
    assert data["status"] in [
        "ISSUED", "ALLOCATED", "DELIVERED", "RECONCILED", "CANCELLED", "DEFAULTED",
    ]


def assert_allocation_line(data: dict):
    """Junction record: id + created_at only, never updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "AllocationLine.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "AllocationLine.created_at must be ISO 8601"
    assert "updated_at" not in data, "allocation lines must not carry updated_at"
    assert "version" not in data, "allocation lines must not carry version"
    assert isinstance(data["delivery_call_id"], str)
    assert isinstance(data["storage_receipt_id"], str)
    assert isinstance(data["allocated_tons"], (int, float))
    assert isinstance(data["shipped_tons"], (int, float))
    assert isinstance(data["shelled_tons"], (int, float))


def assert_settlement(data: dict):
    _assert_common_fields(data, "Settlement")
    assert isinstance(data["grower_id"], str)
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["included_load_ids"], list)
    assert isinstance(data["offset_pledge_ids"], list)
    assert isinstance(data["gross_value_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["drying_cents"], int)
    assert isinstance(data["loan_offset_cents"], int)
    assert isinstance(data["hull_credit_cents"], int)
    assert isinstance(data["net_payment_cents"], int)
    assert isinstance(data["computed_by"], str)
    assert data["status"] in [
        "COMPUTED", "APPROVED", "PAID", "DISPUTED", "STALE", "SUPERSEDED", "VOIDED",
    ]


def assert_quota_history(data: dict):
    _assert_common_fields(data, "QuotaHistory")
    assert isinstance(data["grower_id"], str)
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["quota_tons"], (int, float))
    assert isinstance(data["used_quota_tons"], (int, float))


def assert_hull_lot(data: dict):
    _assert_common_fields(data, "HullLot")
    assert isinstance(data["delivery_call_id"], str)
    assert isinstance(data["tons"], (int, float))
    assert data["status"] in ["GENERATED", "LISTED", "SOLD", "DISPOSED"]
