"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import HEIGHT_CLASS_ORDER


def _assert_common_fields(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an int >= 1"
    )


def assert_season(data: dict):
    _assert_common_fields(data, "Season")
    assert isinstance(data["year"], int)
    assert data["posture"] in [
        "PLANNING", "BOOKING", "HARVEST", "SHIPPING", "SETTLEMENT", "CLOSED",
    ]
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    for field in ("booking_open_at", "booking_close_at",
                  "shipping_window_start", "shipping_window_end"):
        assert isinstance(data[field], str) and len(data[field]) > 0
    for field in ("harvest_window_start", "harvest_window_end"):
        assert isinstance(data[field], str) and len(data[field]) > 0


def assert_block(data: dict):
    _assert_common_fields(data, "Block")
    assert is_valid_uuid(data.get("season_id", "")), "Block.season_id must be a UUID"
    assert isinstance(data["block_code"], str) and len(data["block_code"]) > 0
    assert isinstance(data["ucut_designated"], bool)
    assert data["rotation_state"] in [
        "RESTING", "PLANTED", "GROWING", "HARVESTABLE", "HARVESTED",
    ]


def assert_crop_lot(data: dict):
    _assert_common_fields(data, "CropLot")
    assert is_valid_uuid(data.get("block_id", "")), "CropLot.block_id must be a UUID"
    assert data["species"] in [
        "NOBLE_FIR", "DOUGLAS_FIR", "GRAND_FIR", "NORDMANN_FIR",
    ]
    assert isinstance(data["planted_year"], int)
    assert data["status"] in ["ACTIVE", "DEPLETED"]


def assert_stand_bucket(data: dict):
    _assert_common_fields(data, "StandBucket")
    assert data["height_class"] in HEIGHT_CLASS_ORDER
    for field in ("baseline_count", "standing_count", "reserved_count",
                  "tagged_active_count", "cut_cumulative", "culled_cumulative",
                  "ucut_sold_cumulative", "consigned_cumulative"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"StandBucket.{field} must be a non-negative int"
        )
    assert data["available_count"] == data["standing_count"] - data["reserved_count"], (
        "available_count must equal standing_count - reserved_count"
    )
    assert data.get("last_shrink_delta") is None or isinstance(
        data["last_shrink_delta"], int
    )


def assert_survey(data: dict):
    _assert_common_fields(data, "InventorySurvey")
    assert is_valid_uuid(data.get("crop_lot_id", ""))
    assert data["status"] in ["DRAFT", "POSTED", "SUPERSEDED"]
    counts = data["surveyed_counts"]
    for klass in HEIGHT_CLASS_ORDER:
        assert isinstance(counts[klass], int) and counts[klass] >= 0


def assert_buyer_account(data: dict):
    _assert_common_fields(data, "BuyerAccount")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["standing"] in ["GOOD_STANDING", "CREDIT_HOLD", "CLOSED"]
    assert isinstance(data["exposure_cents"], int) and data["exposure_cents"] >= 0


def assert_order(data: dict):
    _assert_common_fields(data, "WholesaleOrder")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ALLOCATED", "CLOSED", "CANCELLED", "EXPIRED",
    ]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] >= 0


def assert_allocation(data: dict):
    _assert_common_fields(data, "Allocation")
    assert data["status"] in ["RESERVED", "CUT", "LOADED", "RELEASED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["cut_qty"], int) and data["cut_qty"] >= 0
    assert isinstance(data["loaded_qty"], int) and data["loaded_qty"] >= 0


def assert_crew(data: dict):
    _assert_common_fields(data, "Crew")
    assert data["status"] in ["ACTIVE", "LAID_OFF"]
    assert isinstance(data["size"], int) and data["size"] >= 1


def assert_ticket(data: dict):
    _assert_common_fields(data, "HarvestTicket")
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["piece_total_cents"], int)
    assert isinstance(data["hourly_floor_cents"], int)
    assert isinstance(data["gross_pay_cents"], int)
    assert data["gross_pay_cents"] == max(
        data["piece_total_cents"], data["hourly_floor_cents"]
    ), "gross_pay_cents must be max(piece_total_cents, hourly_floor_cents)"
    assert data["pay_basis"] in ["PIECE", "HOURLY_FLOOR"]


def assert_load(data: dict):
    _assert_common_fields(data, "Load")
    assert data["status"] in ["BUILDING", "SHIPPED", "CANCELLED"]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0
    assert data["total_units"] <= data["capacity_units"], (
        "total_units must never exceed capacity_units"
    )
    assert isinstance(data["lines"], list)


def assert_consignment(data: dict):
    _assert_common_fields(data, "Consignment")
    assert data["status"] in [
        "DRAFT", "DELIVERED", "SETTLING", "SETTLED", "DISPUTED",
    ]
    assert isinstance(data["returned_count"], int) and data["returned_count"] >= 0


def assert_ucut_tag(data: dict):
    _assert_common_fields(data, "UcutTag")
    assert data["status"] in ["ACTIVE", "REDEEMED", "RELEASED", "EXPIRED"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_cull_record(data: dict):
    _assert_common_fields(data, "CullRecord")
    assert isinstance(data["count"], int) and data["count"] >= 1
    assert data["reason"] in ["DISEASE", "DAMAGE", "GRADING", "OTHER"]


def assert_replant_plan(data: dict):
    _assert_common_fields(data, "ReplantPlan")
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "EXECUTED"]
    assert isinstance(data["planned_count"], int) and data["planned_count"] >= 1


def assert_bucket_tree_conservation(bucket: dict):
    """Per-bucket physical tree accounting invariant within one epoch:
    baseline == standing + tagged_active + cut + culled + ucut_sold + consigned.
    (Reservations are not physical consumption and are excluded.)"""
    total = (
        bucket["standing_count"]
        + bucket["tagged_active_count"]
        + bucket["cut_cumulative"]
        + bucket["culled_cumulative"]
        + bucket["ucut_sold_cumulative"]
        + bucket["consigned_cumulative"]
    )
    assert bucket["baseline_count"] == total, (
        f"tree conservation violated: baseline {bucket['baseline_count']} != {total}"
    )
