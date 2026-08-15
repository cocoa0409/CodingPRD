"""Entity assertions and domain invariant checkers.

Each assert_* checks the common system-managed fields (PRD section 2.4) plus
the entity's own key fields and enum domains.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_dealership(data: dict):
    _assert_common(data, "Dealership")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["staging_capacity_units"], int)
    assert isinstance(data["standard_labor_rate_cents_per_hour"], int)
    assert isinstance(data["after_hours_start_minute"], int)
    assert isinstance(data["after_hours_multiplier_bp"], int)
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert isinstance(data["credit_cap_pct"], int)


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["dealership_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "CLOSED")
    assert isinstance(data["liquidation_credit_balance_cents"], int)


def assert_pricing_contract(data: dict):
    _assert_common(data, "PricingContract")
    assert isinstance(data["customer_id"], str)
    assert data["contract_type"] in ("STATE", "COOP", "NEGOTIATED")
    assert isinstance(data["pricing_tiers"], list)
    assert isinstance(data["default_discount_pct"], int)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "TERMINATED", "EXPIRED")
    assert isinstance(data["created_by_user_id"], str)


def assert_space_plan(data: dict):
    _assert_common(data, "SpacePlan")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["revision_no"], int)
    assert isinstance(data["budget_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "IN_REVISION", "SUPERSEDED")


def assert_typical(data: dict):
    _assert_common(data, "Typical")
    assert isinstance(data["space_plan_id"], str)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["target_budget_cents_per_instance"], int)
    assert isinstance(data["extended_budget_cents"], int)


def assert_product_series(data: dict):
    _assert_common(data, "ProductSeries")
    assert isinstance(data["dealership_id"], str)
    assert data["manufacturer"] in ("STEELCASE", "MILLERKNOLL")
    assert data["category"] in ("SEATING", "SYSTEMS", "CASEGOODS", "TABLES", "STORAGE")
    assert isinstance(data["series_code"], str) and data["series_code"]
    assert isinstance(data["base_list_price_cents"], int)
    assert isinstance(data["base_lead_time_days"], int)
    assert isinstance(data["option_catalog"], list)
    assert isinstance(data["quality_hold"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_project_order(data: dict):
    _assert_common(data, "ProjectOrder")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["space_plan_id"], str)
    assert isinstance(data["total_list_cents"], int)
    assert isinstance(data["total_net_cents"], int)
    assert isinstance(data["install_fee_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["grand_total_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACKNOWLEDGED", "DELIVERED",
        "INSTALLED", "CLOSED", "CANCELLED",
    )
    assert data["install_posture"] in (
        "NOT_SCHEDULED", "SCHEDULED", "IN_PROGRESS", "COMPLETE", "BLOCKED",
    )


def assert_order_line(data: dict):
    _assert_common(data, "OrderLine")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["series_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["selected_options"], list)
    assert isinstance(data["is_replacement"], bool)
    assert isinstance(data["unit_list_price_cents"], int)
    assert isinstance(data["unit_net_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["received_units"], int)
    assert data["status"] in (
        "OPEN", "PLACED", "ACKNOWLEDGED", "RECEIVED", "CLOSED", "CANCELLED",
    )


def assert_crew(data: dict):
    _assert_common(data, "Crew")
    assert isinstance(data["dealership_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["size"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_install_event(data: dict):
    _assert_common(data, "InstallEvent")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["crew_id"], str)
    assert data["kind"] in ("NEW_INSTALL", "RECONFIGURATION")
    assert isinstance(data["scheduled_date"], str)
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert isinstance(data["after_hours"], bool)
    assert data["status"] in (
        "TENTATIVE", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )


def assert_staging_reservation(data: dict):
    _assert_common(data, "StagingReservation")
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["received_units"], int)
    assert data["status"] in ("RESERVED", "OCCUPIED", "RELEASED", "CANCELLED")


def assert_punch_item(data: dict):
    _assert_common(data, "PunchItem")
    assert isinstance(data["order_id"], str)
    assert data["severity"] in ("STANDARD", "CRITICAL")
    assert isinstance(data["description"], str)
    assert data["source"] in ("INSTALL", "WAREHOUSE")
    assert isinstance(data["affected_units"], int) and data["affected_units"] >= 1
    assert data["status"] in ("OPEN", "READY_FOR_VERIFY", "VERIFIED", "CLOSED")


def assert_manufacturer_claim(data: dict):
    _assert_common(data, "ManufacturerClaim")
    assert isinstance(data["punch_item_id"], str)
    assert data["claim_type"] in ("DEFECT", "FREIGHT_DAMAGE", "SHORTAGE")
    assert data["remedy_requested"] in ("REPAIR", "REPLACE", "CREDIT")
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["origin"] in ("MANUAL", "AUTO_CRITICAL_PUNCH")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACKNOWLEDGED", "SETTLEMENT_OFFERED",
        "SETTLED", "DENIED", "WITHDRAWN",
    )


def assert_asset_tag(data: dict):
    _assert_common(data, "AssetTag")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["description"], str)
    assert data["condition"] in ("NEW", "GOOD", "FAIR", "POOR")
    assert isinstance(data["current_location"], str)
    assert data["source"] in ("PURCHASED", "TRADED_IN")
    assert data["status"] in ("IN_SERVICE", "IN_STORAGE", "DISPOSED")


def assert_liquidation_lot(data: dict):
    _assert_common(data, "LiquidationLot")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1
    assert isinstance(data["estimated_credit_cents"], int)
    assert isinstance(data["redeemed_cents"], int)
    assert data["status"] in (
        "OFFERED", "APPRAISED", "CREDIT_ISSUED", "REDEEMED", "DECLINED", "EXPIRED",
    )


def assert_order_totals_invariants(order: dict):
    """Domain invariants on the order rollup (PRD section 3.4)."""
    assert order["grand_total_cents"] == (
        order["total_net_cents"]
        + order["install_fee_cents"]
        - order["credit_applied_cents"]
    ), "grand_total_cents must equal net + fee - credit_applied"
    assert order["credit_applied_cents"] >= 0
    assert order["total_net_cents"] >= 0
