"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, mutable: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    if mutable:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be a positive integer"


def assert_branch(data: dict):
    _assert_common(data)
    assert isinstance(data["branch_code"], str) and data["branch_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["rooftop_delivery_capacity_per_day"], int)
    assert isinstance(data["conveyor_fleet_size"], int)
    assert isinstance(data["crane_available"], bool)
    assert data["surge_mode"] in ("NORMAL", "SURGE")
    assert data["status"] == "ACTIVE"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["manufacturer_name"], str) and data["manufacturer_name"]
    assert isinstance(data["color_code"], str) and data["color_code"]
    assert isinstance(data["bundles_per_square"], (int, float))
    assert isinstance(data["base_price_per_bundle_cents"], int)
    assert isinstance(data["requires_certified_installer"], bool)
    assert data["status"] == "ACTIVE"


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", "")), "branch_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["on_hand_bundles"], int) and data["on_hand_bundles"] >= 0
    assert isinstance(data["reserved_bundles"], int) and data["reserved_bundles"] >= 0
    # PRD §2.7: read-only available = on_hand - reserved, floored at zero.
    assert data["available_bundles"] == max(
        0, data["on_hand_bundles"] - data["reserved_bundles"]), \
        "available_bundles must equal on_hand - reserved floored at 0"


def assert_contractor_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_balance_cents"], int)
    assert isinstance(data["pending_delivery_hold_cents"], int)
    assert isinstance(data["lien_hold_cents"], int)
    assert data["pricing_tier"] in ("STANDARD", "PREFERRED", "VOLUME")
    assert isinstance(data["manufacturer_certifications"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "LIEN_DEFAULT")


def assert_job_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contractor_account_id", ""))
    assert isinstance(data["job_name"], str) and data["job_name"]
    assert isinstance(data["site_address"], str) and data["site_address"]
    assert isinstance(data["job_balance_cents"], int) and data["job_balance_cents"] >= 0
    assert data["lien_status"] in ("NONE", "NOTICE_FILED", "LIEN_RECORDED", "RELEASED")
    assert isinstance(data["lien_notice_amount_cents"], int)


def assert_takeoff(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_account_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["roof_squares"], (int, float))
    assert isinstance(data["waste_factor_pct"], (int, float))
    assert isinstance(data["valley_ridge_linear_feet"], int)
    assert isinstance(data["estimated_bundles"], int) and data["estimated_bundles"] >= 0
    assert isinstance(data["estimated_amount_cents"], int)
    assert data["status"] in ("DRAFT", "QUOTED", "CONVERTED", "EXPIRED")


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("job_account_id", ""))
    assert is_valid_uuid(data.get("branch_id", ""))
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["delivery_fee_cents"], int)
    assert isinstance(data["surge_premium_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["fulfillment_status"] in (
        "UNFULFILLED", "PARTIALLY_DELIVERED", "DELIVERED", "RETURN_ADJUSTED")
    assert data["payment_status"] in ("UNPAID", "INVOICED", "PAID", "CREDITED")
    assert data["status"] in ("QUOTED", "CONFIRMED", "CLOSED", "CANCELLED")


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["quantity_bundles"], int) and data["quantity_bundles"] > 0
    assert isinstance(data["delivered_bundles"], int) and data["delivered_bundles"] >= 0
    assert isinstance(data["returned_bundles"], int) and data["returned_bundles"] >= 0


def assert_delivery_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert isinstance(data["slot_date"], str) and data["slot_date"]
    assert data["window"] in ("AM", "PM")
    assert data["equipment_type"] in ("GROUND", "ROOFTOP_CONVEYOR", "CRANE")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0


def assert_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("delivery_slot_id", ""))
    assert data["equipment_type"] in ("GROUND", "ROOFTOP_CONVEYOR", "CRANE")
    assert isinstance(data["bundle_count"], int) and data["bundle_count"] >= 0
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["crane_fee_cents"], int)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "DELIVERED", "FAILED", "RESCHEDULED", "CANCELLED")


def assert_surge_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert isinstance(data["event_name"], str) and data["event_name"]
    assert isinstance(data["surge_multiplier_pct"], int)
    assert isinstance(data["allocation_pool_bundles"], int)
    assert isinstance(data["allocated_bundles"], int) and data["allocated_bundles"] >= 0
    assert data["status"] in ("DECLARED", "ACTIVE", "CLOSED")


def assert_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("storm_surge_event_id", ""))
    assert is_valid_uuid(data.get("contractor_account_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["requested_bundles"], int) and data["requested_bundles"] > 0
    assert isinstance(data["granted_bundles"], int) and data["granted_bundles"] >= 0
    assert isinstance(data["consumed_bundles"], int) and data["consumed_bundles"] >= 0
    assert data["status"] in (
        "PENDING", "GRANTED", "PARTIALLY_CONSUMED", "CONSUMED", "EXPIRED", "REVOKED")


def assert_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert isinstance(data["quantity_bundles"], int) and data["quantity_bundles"] > 0
    assert isinstance(data["opened_bundles"], int) and data["opened_bundles"] >= 0
    assert isinstance(data["lot_match_verified"], bool)
    assert isinstance(data["credit_amount_cents"], int) and data["credit_amount_cents"] >= 0
    assert data["status"] in ("REQUESTED", "APPROVED", "RECEIVED", "REJECTED")


def assert_damage_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("delivery_id", ""))
    assert isinstance(data["claimed_bundles"], int) and data["claimed_bundles"] > 0
    assert isinstance(data["claim_amount_cents"], int)
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "APPROVED", "REJECTED", "DISPUTED", "CREDITED")


def assert_warranty_registration(data: dict):
    """PRD §2.5: immutable — carries only id + created_at; both updated_at and
    version are absent from it."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "WarrantyRegistration must not carry updated_at"
    assert "version" not in data, "WarrantyRegistration must not carry version"
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["manufacturer_name"], str) and data["manufacturer_name"]
    assert isinstance(data["registered_bundles"], int) and data["registered_bundles"] >= 0
    assert isinstance(data["certification_verified"], bool)


def assert_credit_ledger_invariants(data: dict):
    """PRD §2.8: entity-level credit_available is the conservative reading —
    limit minus open balance, minus pending delivery hold, minus lien hold."""
    assert data["credit_available_cents"] == (
        data["credit_limit_cents"]
        - data["open_balance_cents"]
        - data["pending_delivery_hold_cents"]
        - data["lien_hold_cents"]), "credit_available_cents must follow the ledger rule"
    assert data["open_balance_cents"] >= 0
    assert data["pending_delivery_hold_cents"] >= 0
    assert data["lien_hold_cents"] >= 0
