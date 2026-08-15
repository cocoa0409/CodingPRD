"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Common server-managed properties present on every resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_seed_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["crop_year"], int)
    assert data["status"] in ["DRAFT", "OPEN", "SALES_CLOSED", "SETTLED"]
    assert isinstance(data["early_order_tiers"], list)
    assert isinstance(data["prepay_tiers"], list)
    assert isinstance(data["volume_rebate_tiers"], list)
    assert isinstance(data["commission_volume_tiers"], list)
    assert isinstance(data["return_restocking_bps"], int)
    assert isinstance(data["returns_untreated_only"], bool)
    assert isinstance(data["replant_claim_window_days"], int)
    assert isinstance(data["replant_replacement_discount_bps"], int)
    assert isinstance(data["daily_delivery_capacity_units"], int)
    assert isinstance(data["commission_base_bps"], int)
    assert isinstance(data["min_plot_replications"], int)


def assert_grower_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD", "INACTIVE"]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["prepay_balance_cents"], int)


def assert_field(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["acres"] > 0
    assert data["soil_type"] in ["CLAY", "LOAM", "SAND", "SILT"]
    assert data["drainage"] in ["POOR", "MODERATE", "WELL"]
    assert isinstance(data["irrigated"], bool)
    assert data["prev_crop"] in ["CORN", "SOYBEAN", "WHEAT", "FALLOW", "OTHER"]
    assert isinstance(data["maturity_zone"], int) and 1 <= data["maturity_zone"] <= 13
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_trait_package(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["description"], str)
    assert isinstance(data["requires_stewardship_agreement"], bool)
    assert isinstance(data["refuge_required_bps"], int)
    assert data["status"] in ["LISTED", "RETIRED"]


def assert_variety(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["crop"] in ["CORN", "SOYBEAN"]
    assert isinstance(data["relative_maturity_days"], int)
    assert data.get("trait_package_id") is None or is_valid_uuid(data["trait_package_id"])
    assert isinstance(data["base_price_cents_per_unit"], int)
    assert isinstance(data["seeds_per_unit"], int)
    assert isinstance(data["preferred_soils"], list)
    assert data["min_drainage"] in ["POOR", "MODERATE", "WELL"]
    assert data["status"] in ["LISTED", "DELISTED"]


def assert_trait_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", ""))
    assert is_valid_uuid(data.get("trait_package_id", ""))
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert data["status"] in [
        "PENDING_SIGNATURE", "ACTIVE", "SUSPENDED", "SUPERSEDED", "EXPIRED", "REVOKED",
    ]


def assert_placement_recommendation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("field_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("grower_id", ""))
    assert isinstance(data["seeding_rate_seeds_per_acre"], int)
    assert isinstance(data["placement_score"], (int, float))
    assert 0 <= data["placement_score"] <= 100
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "ACCEPTED", "SUPERSEDED", "WITHDRAWN", "EXPIRED",
    ]


def assert_seed_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["is_replacement"], bool)
    assert data["status"] in ["DRAFT", "CONFIRMED", "COMPLIANCE_HOLD", "CLOSED", "CANCELLED"]
    assert data["payment_status"] in ["UNPAID", "PREPAID", "INVOICED", "SETTLED"]
    assert data["fulfillment_status"] in [
        "NONE", "PARTIAL", "DELIVERED", "RETURNED_PARTIAL", "RETURNED_FULL",
    ]
    for money in (
        "gross_amount_cents", "rebate_amount_cents", "prepay_discount_cents",
        "net_amount_cents", "prepaid_amount_cents", "paid_amount_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be integer cents"
    assert isinstance(data["total_units"], int)
    assert isinstance(data["locked_discount_bps"], int)
    assert isinstance(data["rebate_bps_applied"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert data.get("treatment_option_id") is None or is_valid_uuid(data["treatment_option_id"])
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["delivered_units"], int)
    assert isinstance(data["returned_units"], int)


def assert_treatment_option(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["crop"] in ["CORN", "SOYBEAN"]
    assert isinstance(data["adder_cents_per_unit"], int)
    assert data["status"] in ["AVAILABLE", "DISCONTINUED"]


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("variety_id", ""))
    assert data.get("treatment_option_id") is None or is_valid_uuid(data["treatment_option_id"])
    assert isinstance(data["warehouse_code"], str)
    for counter in (
        "received_units", "on_hand_units", "reserved_units",
        "delivered_units", "returned_units", "written_off_units",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    assert data["status"] in ["AVAILABLE", "QUARANTINED", "DEPLETED", "EXPIRED"]


def assert_delivery_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert data["type"] in ["DELIVERY", "PICKUP"]
    assert is_iso8601_timestamp(data.get("scheduled_date", ""))
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_seed_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["reason"] in ["OVERSTOCK", "WRONG_HYBRID", "DAMAGED", "OTHER"]
    assert data["status"] in ["REQUESTED", "APPROVED", "RECEIVED", "CREDITED", "REJECTED"]


def assert_replant_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert is_valid_uuid(data.get("field_id", ""))
    assert data["event_type"] in ["FROST", "FLOOD", "HAIL", "DROUGHT", "PEST"]
    assert data["acres_affected"] > 0
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED", "WITHDRAWN",
    ]


def assert_plot_trial(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("variety_id", ""))
    assert is_valid_uuid(data.get("field_id", ""))
    assert is_iso8601_timestamp(data.get("planting_date", ""))
    assert is_iso8601_timestamp(data.get("expected_harvest_date", ""))
    assert isinstance(data["replication_index"], int)
    assert data["status"] in ["PLANNED", "PLANTED", "HARVESTED", "PUBLISHED", "DISCARDED"]


def assert_commission_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["status"] in ["ACCRUING", "FINALIZED", "PAID"]
    for money in (
        "gross_sales_cents", "return_credits_cents", "net_sales_cents",
        "base_commission_cents", "volume_bonus_cents", "total_commission_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be integer cents"
    assert isinstance(data["volume_units"], int)
    assert isinstance(data["volume_bonus_bps"], int)


# ─── Domain invariants (PRD §2.9 conservation ledgers) ──

def assert_lot_seed_conservation(lot: dict):
    """For every inventory lot, received_units plus returned_units always equals
    on_hand_units plus delivered_units plus written_off_units (PRD §2.9)."""
    lhs = lot["received_units"] + lot["returned_units"]
    rhs = lot["on_hand_units"] + lot["delivered_units"] + lot["written_off_units"]
    assert lhs == rhs, (
        f"Seed conservation violated: received {lot['received_units']} + returned "
        f"{lot['returned_units']} != on_hand {lot['on_hand_units']} + delivered "
        f"{lot['delivered_units']} + written_off {lot['written_off_units']}"
    )
    assert lot["reserved_units"] <= lot["on_hand_units"], (
        "Reservations are a subset of on-hand units (PRD §2.9)"
    )
