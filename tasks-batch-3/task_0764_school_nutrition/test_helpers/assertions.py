"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty"
    assert isinstance(data["site_code"], str) and data["site_code"], "site_code must be non-empty"
    assert isinstance(data["negative_balance_count"], int)
    assert data["negative_balance_count"] >= 0, "negative_balance_count must be non-negative"


def assert_food_item(data: dict):
    _assert_common(data)
    assert data["category"] in [
        "ENTREE", "GRAIN", "FRUIT", "VEGETABLE", "MILK", "SNACK", "BEVERAGE",
    ]


def assert_reimbursement_rate(data: dict):
    _assert_common(data)
    assert data["program"] in ["NSLP", "SBP"]
    assert data["category"] in ["FREE", "REDUCED", "PAID"]
    assert isinstance(data["rate_cents"], int)


def assert_menu_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "UNDER_REVIEW", "APPROVED"]
    assert data["compliance_status"] in ["COMPLIANT", "NONCOMPLIANT"]
    assert data["meal_type"] in ["BREAKFAST", "LUNCH"]
    assert data["grade_group"] in ["GRADES_K_5", "GRADES_6_8", "GRADES_9_12"]


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert data["lot_type"] in ["COMMODITY_USDA_FOODS", "PURCHASED"]
    assert data["status"] in ["AVAILABLE", "DEPLETED"]
    assert data["quantity_on_hand"] >= 0, "quantity_on_hand must never go negative"
    # Invariant: a lot is DEPLETED exactly when on-hand hits 0 (PRD §3.3).
    if data["quantity_on_hand"] == 0:
        assert data["status"] == "DEPLETED", "on-hand 0 implies DEPLETED"
    else:
        assert data["status"] == "AVAILABLE", "positive on-hand implies AVAILABLE"


def assert_production_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "PREPARED", "CANCELLED"]
    assert data["meal_type"] in ["BREAKFAST", "LUNCH"]
    assert data["served_qty"] >= 0
    assert data["leftover_qty"] >= 0, "leftover_qty is never below zero (PRD §3.4)"


def assert_student(data: dict):
    _assert_common(data)
    assert data["eligibility_category"] in ["FREE", "REDUCED", "PAID"]
    assert data["account_status"] in ["ACTIVE", "LOW_BALANCE", "NEGATIVE"]
    assert isinstance(data["balance_cents"], int)
    assert_account_status_consistent(data)


def assert_account_status_consistent(data: dict):
    """PRD §3.5: NEGATIVE if balance<0; LOW_BALANCE if 0<=balance<=threshold; else ACTIVE."""
    balance = data["balance_cents"]
    threshold = data["low_balance_threshold_cents"]
    status = data["account_status"]
    if balance < 0:
        expected = "NEGATIVE"
    elif balance <= threshold:
        expected = "LOW_BALANCE"
    else:
        expected = "ACTIVE"
    assert status == expected, (
        f"account_status {status} inconsistent with balance {balance} / threshold {threshold} "
        f"(expected {expected})"
    )


def assert_meal_transaction(data: dict):
    _assert_common(data)
    assert data["meal_claim_status"] in ["REIMBURSABLE", "NON_REIMBURSABLE", "VOIDED"]
    assert data["claim_category"] in ["FREE", "REDUCED", "PAID"]
    assert data["payment_status"] in ["PAID", "CHARGED", "REFUNDED", "VOIDED"]
    assert isinstance(data["meal_charge_cents"], int)
    assert isinstance(data["alacarte_total_cents"], int)


def assert_reimbursement_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "PAID"]
    assert isinstance(data["free_count"], int)
    assert isinstance(data["reduced_count"], int)
    assert isinstance(data["paid_count"], int)
