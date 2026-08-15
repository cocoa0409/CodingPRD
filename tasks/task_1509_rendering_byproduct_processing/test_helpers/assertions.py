"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_plant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plant_name"], str) and data["plant_name"]
    assert isinstance(data["location"], str)
    assert isinstance(data["cooker_capacity"], int) and data["cooker_capacity"] >= 1
    assert isinstance(data["standard_cost_cents_per_lb"], int)
    assert isinstance(data["odor_score"], int) and 0 <= data["odor_score"] <= 1000
    assert data["posture"] in ["OPERATING", "RESTRICTED", "SUSPENDED", "DECOMMISSIONED"]
    assert isinstance(data["current_period_index"], int) and data["current_period_index"] >= 1


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["permit_number"], str)
    assert isinstance(data["odor_event_threshold"], int) and data["odor_event_threshold"] >= 1
    assert isinstance(data["confirmed_violation_count"], int)
    assert data["status"] in [
        "DRAFT", "PENDING_ISSUANCE", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED",
    ]


def assert_supplier(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["supplier_type"] in ["FARM", "SLAUGHTERHOUSE", "BUTCHER_SHOP", "GROCERY"]
    assert isinstance(data["contamination_strikes"], int) and data["contamination_strikes"] >= 0
    assert isinstance(data["outstanding_service_fees_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["agreement_ref"], str)
    assert isinstance(data["species_scope"], list) and len(data["species_scope"]) >= 1
    assert data["prohibited_material_policy"] in ["ZERO_TOLERANCE", "SORT_AND_RETURN"]
    assert isinstance(data["accepts_dead_stock"], bool)
    assert isinstance(data["pickup_base_fee_cents"], int)
    assert isinstance(data["per_lb_fee_cents"], int)
    assert isinstance(data["mileage_rate_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["vehicle_tag"], str)
    assert isinstance(data["capacity_lbs"], int) and data["capacity_lbs"] >= 1
    assert data["duty_class"] in ["RAW_MATERIAL", "FINISHED_PRODUCT", "DUAL"]
    assert data["sanitation_status"] in ["SANITIZED", "DIRTY", "QUARANTINED"]
    assert isinstance(data["completed_trip_count"], int) and data["completed_trip_count"] >= 0


def assert_wash_ticket(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["plant_id"])
    assert data["wash_type"] in ["STANDARD", "DEEP"]
    assert data["result"] in ["PASS", "FAIL"]
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]


def assert_route(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["route_code"], str)
    assert isinstance(data["total_collected_lbs"], int)
    assert data["status"] in ["PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


def assert_stop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["estimated_weight_lbs"], int) and data["estimated_weight_lbs"] >= 1
    assert isinstance(data["estimated_distance_miles"], int)
    assert data["species_tag"] in ["BOVINE", "PORCINE", "POULTRY", "OVINE", "MIXED"]
    assert isinstance(data["is_dead_stock"], bool)
    assert isinstance(data["provisional_fee_cents"], int)
    assert data["status"] in [
        "SCHEDULED", "ARRIVED", "COLLECTED", "DELIVERED",
        "REJECTED_AT_SITE", "MISSED", "CANCELLED", "VOIDED",
    ]


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert data["species"] in ["BOVINE", "PORCINE", "POULTRY", "OVINE", "MIXED"]
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] >= 1
    assert data["screening_result"] in ["PENDING", "PASS", "FAIL_PROHIBITED", "FAIL_TEMPERATURE"]
    assert isinstance(data["reserved_lbs"], int) and data["reserved_lbs"] >= 0
    assert isinstance(data["consumed_lbs"], int) and data["consumed_lbs"] >= 0
    assert isinstance(data["remaining_lbs"], int) and data["remaining_lbs"] >= 0
    assert data["status"] in ["RECEIVED", "ACCEPTED", "QUARANTINED", "REJECTED", "DEPLETED"]


def assert_cook_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["cooker_line"], int) and data["cooker_line"] >= 1
    assert data["recipe"] in [
        "RUMINANT_RENDER", "PORCINE_RENDER", "POULTRY_RENDER", "MIXED_RENDER",
    ]
    assert isinstance(data["planned_inputs"], list) and len(data["planned_inputs"]) >= 1
    assert isinstance(data["total_input_lbs"], int)
    assert isinstance(data["theoretical_fat_lbs"], int)
    assert isinstance(data["theoretical_meal_lbs"], int)
    assert isinstance(data["recook_count"], int) and data["recook_count"] >= 0
    assert data["status"] in [
        "STAGED", "COOKING", "SETTLING", "PRESSING", "COMPLETED", "FAILED", "CANCELLED",
    ]


def assert_product_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert is_valid_uuid(data["cook_run_id"])
    assert data["product_type"] in ["TALLOW", "YELLOW_GREASE", "PROTEIN_MEAL", "FEATHER_MEAL"]
    assert isinstance(data["quantity_lbs"], int)
    assert isinstance(data["available_lbs"], int) and data["available_lbs"] >= 0
    assert isinstance(data["allocated_lbs"], int) and data["allocated_lbs"] >= 0
    assert data["grade"] in ["UNGRADED", "PREMIUM", "STANDARD", "FEED_GRADE", "OFF_SPEC"]
    assert data["status"] in [
        "LAB_PENDING", "GRADED", "RELEASED", "DOWNGRADED", "REJECTED", "DEPLETED",
    ]


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["customer_name"], str)
    assert data["product_type"] in ["TALLOW", "YELLOW_GREASE", "PROTEIN_MEAL", "FEATHER_MEAL"]
    assert data["pricing_mode"] in ["FIXED", "INDEX_LINKED"]
    assert isinstance(data["tier_discounts"], list)
    assert isinstance(data["delivered_volume_lbs"], int)
    assert isinstance(data["created_by"], str) and data["created_by"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_sales_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["quantity_lbs"], int) and data["quantity_lbs"] >= 1
    assert isinstance(data["requested_ship_date"], str)
    assert data["status"] in ["DRAFT", "PRICED", "CONFIRMED", "SHIPPED", "INVOICED", "CANCELLED"]


def assert_price_index_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert data["index_product"] in ["TALLOW", "MEAL"]
    assert isinstance(data["price_cents_per_lb"], int) and data["price_cents_per_lb"] >= 1
    assert data["source"] in ["USDA_AMS", "JACOBSEN", "INTERNAL"]
    assert isinstance(data["published_by"], str) and data["published_by"]


def assert_odor_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["reported_by"], str) and data["reported_by"]
    assert data["status"] in ["REPORTED", "CONFIRMED", "DISMISSED"]


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["pickup_fees_accrued_cents"], int)
    assert isinstance(data["product_revenue_cents"], int)
    assert isinstance(data["energy_costs_cents"], int)
    assert isinstance(data["transport_costs_cents"], int)
    assert isinstance(data["confirmed_odor_events"], int)
    assert isinstance(data["gross_margin_cents"], int)
    assert data["status"] in ["OPEN", "CLOSED", "REOPENED", "FINALIZED"]


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.11)
# ---------------------------------------------------------------------------
def assert_batch_mass_conserved(batch: dict):
    """weight_lbs == remaining_lbs + reserved_lbs + consumed_lbs at all times."""
    total = batch["remaining_lbs"] + batch["reserved_lbs"] + batch["consumed_lbs"]
    assert total == batch["weight_lbs"], (
        f"Batch mass not conserved: {batch['weight_lbs']} != "
        f"{batch['remaining_lbs']} + {batch['reserved_lbs']} + {batch['consumed_lbs']}"
    )


def assert_settlement_margin_consistency(settlement: dict):
    """gross_margin_cents = revenue + fees - energy - transport (PRD §3.1)."""
    expected = (
        settlement["product_revenue_cents"]
        + settlement["pickup_fees_accrued_cents"]
        - settlement["energy_costs_cents"]
        - settlement["transport_costs_cents"]
    )
    assert settlement["gross_margin_cents"] == expected, (
        f"gross_margin_cents {settlement['gross_margin_cents']} != {expected}"
    )
