"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.5: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_salon_account(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert data["status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "DEACTIVATED")
    assert data["tier"] in ("SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["tier_override_active"], bool)
    assert isinstance(data["education_credit_points"], int)
    assert isinstance(data["diversion_strike_points"], int)
    assert isinstance(data["diversion_risk_score"], (int, float))
    assert isinstance(data["trailing_12m_delivered_volume_cents"], int)
    assert "suspension_reason" in data
    if data["suspension_reason"] is not None:
        assert data["suspension_reason"] in (
            "MANUAL", "LICENSE_EXPIRED", "DIVERSION_STRIKES")
    assert "assigned_consultant_id" in data


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["salon_account_id"], str)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["issuing_state"], str)
    assert data["license_type"] in (
        "COSMETOLOGY", "ESTHETICIAN", "BARBER", "NAIL_TECH", "SALON_BUSINESS")
    assert isinstance(data["valid_until"], str)
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")
    assert "reviewed_by_user_id" in data


def assert_brand(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert "discontinued_at" in data


def assert_territory_exclusive(data: dict):
    _assert_common(data)
    assert isinstance(data["brand_id"], str)
    assert isinstance(data["territory_code"], str)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["brand_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["variant_type"] in ("BACKBAR", "RETAIL")
    assert data["hazmat_class"] in ("NONE", "AEROSOL", "FLAMMABLE_LIQUID")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] > 0
    assert data["lifecycle_status"] in (
        "ACTIVE", "DISCONTINUED", "LIQUIDATION", "ARCHIVED")
    assert "discontinued_at" in data
    assert "liquidation_started_at" in data


def assert_consultant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["territory_codes"], list) and data["territory_codes"]
    assert data["commission_model"] in ("STRAIGHT", "ACCELERATOR")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["commission_accrued_cents"], int)
    assert "commission_month" in data
    assert isinstance(data["commission_month_volume_cents"], int)


def assert_route_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["sales_consultant_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "COMPLETED")


def assert_route_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["route_plan_id"], str)
    assert isinstance(data["salon_account_id"], str)
    assert isinstance(data["start_at"], str)
    assert isinstance(data["end_at"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert "visited_at" in data


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["salon_account_id"], str)
    assert data["fulfillment_status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "FULFILLING", "SHIPPED",
        "DELIVERED", "CANCELLED", "REJECTED")
    assert data["payment_status"] in (
        "UNPAID", "AUTHORIZED", "CAPTURED", "VOIDED", "REFUNDED")
    for field in ("merchandise_total_cents", "credit_applied_cents",
                  "net_merch_cents", "shipping_total_cents",
                  "grand_total_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert "promo_applied_code" in data
    assert "submitted_at" in data
    assert "delivered_at" in data


def assert_order_item(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["is_promotional"], bool)


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert data["method"] in ("GROUND", "AIR")
    assert isinstance(data["items"], list)
    assert data["status"] in ("PLANNED", "LABEL_CREATED", "IN_TRANSIT", "DELIVERED")
    assert isinstance(data["hazmat_declaration_required"], bool)
    assert isinstance(data["hazmat_surcharge_cents"], int)
    assert isinstance(data["shipping_charge_cents"], int)


def assert_promotion(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["promo_type"] in ("BUNDLE", "SAMPLE")
    assert isinstance(data["eligible_tiers"], list) and data["eligible_tiers"]
    for tier in data["eligible_tiers"]:
        assert tier in ("SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert isinstance(data["budget_units"], int) and data["budget_units"] > 0
    assert isinstance(data["per_salon_cap"], int) and data["per_salon_cap"] > 0
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "ENDED")
    assert "remaining_budget_units" in data


def assert_redemption(data: dict):
    _assert_common(data)
    assert isinstance(data["promotion_id"], str)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["salon_account_id"], str)
    assert isinstance(data["units_consumed"], int)
    assert data["status"] in ("APPLIED", "REVERSED")
    assert "reversal_reason" in data
    if data["reversal_reason"] is not None:
        assert data["reversal_reason"] in (
            "ORDER_CANCELLED", "ORDER_REJECTED", "ACCOUNT_SUSPENDED")


def assert_credit_entry(data: dict):
    """EducationCreditEntry is append-only (PRD §2.5): id + created_at only,
    no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data["salon_account_id"], str)
    assert "order_id" in data
    assert data["entry_type"] in (
        "PROVISIONAL_ACCRUAL", "FINAL_ACCRUAL", "REDEMPTION", "REVERSAL", "EXPIRY")
    assert isinstance(data["points"], int)
    assert isinstance(data["consumed_points"], int)
    assert isinstance(data["earned_at"], str)
    assert "expires_at" in data


def assert_diversion_case(data: dict):
    _assert_common(data)
    assert isinstance(data["salon_account_id"], str)
    assert isinstance(data["product_id"], str)
    assert "filed_by_consultant_id" in data
    assert isinstance(data["filed_by_user_id"], str)
    assert data["severity"] in ("MINOR", "MAJOR", "SEVERE")
    assert isinstance(data["evidence_note"], str)
    assert isinstance(data["hold_shipments"], bool)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
    assert "adjudicated_by_user_id" in data
    assert isinstance(data["strike_points_awarded"], int)


def assert_credit_ledger_invariant(entries: list, expected_balance: int):
    """PRD §3.9: the salon's education_credit_points is always the signed sum
    of points across all its ledger entries."""
    signed_sum = sum(e["points"] for e in entries)
    assert signed_sum == expected_balance, (
        f"Ledger signed sum {signed_sum} != expected balance {expected_balance}")
