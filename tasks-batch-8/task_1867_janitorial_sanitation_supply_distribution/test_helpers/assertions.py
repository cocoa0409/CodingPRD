"""Entity assertions and domain invariant checkers.

Every resource carries the system-managed fields id / created_at /
updated_at / version (PRD section on resource identity and common fields);
each assert_{entity} checks those shapes plus the entity's own field types
and enum memberships.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer")


def assert_facility(data: dict):
    _assert_common_fields(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["facility_group_code"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["service_zone"], str)
    assert isinstance(data["delivery_distance_miles"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ARCHIVED")
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert isinstance(data["closed_loop_enrolled"], bool)


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("CHEMICAL", "PAPER", "EQUIPMENT",
                                "DISPENSER_SUPPLY", "OTHER")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["unit_of_measure"], str)
    assert isinstance(data["dilution_required"], bool)
    assert data["chemical_family"] in ("ACID", "ALKALINE", "NEUTRAL",
                                       "OXIDIZER", "NONE")
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert isinstance(data["qty_allocated"], int) and data["qty_allocated"] >= 0
    assert data["status"] in ("ACTIVE", "SHORTAGE", "DISCONTINUED")


def assert_usage_record(data: dict):
    _assert_common_fields(data, "UsageRecord")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["quantity_used"], int) and data["quantity_used"] >= 1
    assert data["source"] in ("MANUAL", "AUTO_DISPENSER")
    assert data["status"] in ("SUBMITTED", "POSTED")


def assert_forecast_profile(data: dict):
    _assert_common_fields(data, "ForecastProfile")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["horizon_days"], int) and data["horizon_days"] >= 1
    assert isinstance(data["safety_stock"], int) and data["safety_stock"] >= 0
    assert isinstance(data["current_on_hand"], int) and data["current_on_hand"] >= 0


def assert_technician(data: dict):
    _assert_common_fields(data, "Technician")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_dispenser(data: dict):
    _assert_common_fields(data, "Dispenser")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["zone"], str) and data["zone"]
    assert is_valid_uuid(data.get("technician_id", ""))
    assert data["status"] in ("SCHEDULED", "INSTALLED", "DECOMMISSIONED")


def assert_training_record(data: dict):
    _assert_common_fields(data, "TrainingRecord")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["employee_name"], str) and data["employee_name"]
    assert data["status"] in ("SCHEDULED", "CERTIFIED", "FAILED", "EXPIRED")


def assert_standing_order(data: dict):
    _assert_common_fields(data, "StandingOrder")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["items"], list) and len(data["items"]) >= 1
    assert data["frequency"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "CANCELLED")
    assert data["pause_reason"] in ("NONE", "MANUAL", "SUSPENSION")
    assert isinstance(data["price_protected"], bool)
    assert isinstance(data["next_delivery_total_cents"], int)


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["source"] in ("MANUAL", "STANDING_ORDER", "TRIAL_CONVERSION")
    assert data["status"] in ("DRAFT", "PLACED", "PARTIALLY_BLOCKED",
                              "DELIVERED", "INVOICED", "CANCELLED")
    for field in ("merchandise_subtotal_cents", "delivery_fee_cents",
                  "fuel_surcharge_cents", "trial_credit_cents", "total_cents"):
        assert isinstance(data[field], int), f"Order.{field} must be int cents"
        assert data[field] >= 0, f"Order.{field} must be non-negative"


def assert_order_line(data: dict):
    _assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in ("PENDING", "ALLOCATED", "SUBSTITUTION_PENDING",
                              "FULFILLED", "CANCELLED")


def assert_contract_bid(data: dict):
    _assert_common_fields(data, "ContractBid")
    assert isinstance(data["bid_reference"], str) and data["bid_reference"]
    assert isinstance(data["facility_group_code"], str)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "AWARDED",
                              "LOST", "EXPIRED", "TERMINATED")
    assert isinstance(data["revision_number"], int)


def assert_substitution_proposal(data: dict):
    _assert_common_fields(data, "SubstitutionProposal")
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert is_valid_uuid(data.get("original_product_id", ""))
    assert is_valid_uuid(data.get("proposed_product_id", ""))
    assert isinstance(data["price_delta_cents"], int)
    assert data["status"] in ("PENDING", "ACCEPTED", "DECLINED", "EXPIRED")


def assert_trial_program(data: dict):
    _assert_common_fields(data, "TrialProgram")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["sample_value_cents"], int)
    assert data["sample_value_cents"] >= 0
    assert data["status"] in ("ACTIVE", "CONVERTED", "EXPIRED")
    assert isinstance(data["conversion_credit_cents"], int)


def assert_stock_conserved(product: dict, original_on_hand: int):
    """Stock invariant: qty_on_hand + qty_allocated is conserved across
    allocate/deallocate; fulfillment decrements qty_allocated only."""
    assert product["qty_on_hand"] >= 0, "qty_on_hand never goes negative"
    assert product["qty_allocated"] >= 0, "qty_allocated never goes negative"
    assert product["qty_on_hand"] + product["qty_allocated"] <= original_on_hand


def assert_ledger_balances(facility: dict):
    """Facility ledger counters are never negative."""
    assert facility["committed_cents"] >= 0
    assert facility["outstanding_cents"] >= 0
