"""Entity assertions and domain invariant checkers (Rent-To-Own Home PRD)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """§2.4: every primary resource carries id (UUID, no prefix), created_at,
    updated_at (ISO 8601), and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_landlord(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["payout_account_ref"], str)


def assert_tenant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["credit_score"], int)
    assert 300 <= data["credit_score"] <= 850


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["landlord_id"], str)
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["status"] in ("AVAILABLE", "UNDER_AGREEMENT", "SOLD")


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["tenant_id"], str)
    assert isinstance(data["landlord_id"], str)
    assert isinstance(data["locked_price_cents"], int)
    assert isinstance(data["option_fee_cents"], int)
    assert isinstance(data["option_fee_creditable"], bool)
    assert isinstance(data["monthly_payment_cents"], int)
    assert data["status"] in (
        "DRAFT", "ACTIVE", "EXERCISED", "CONVERTED", "DEFAULTED", "EXPIRED"
    )
    assert isinstance(data["missed_payment_count"], int)
    assert isinstance(data["gross_credit_accrued_cents"], int)
    assert isinstance(data["available_credit_cents"], int)


def assert_rent_payment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["rent_portion_cents"], int)
    assert isinstance(data["credit_portion_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert data["status"] in ("PENDING", "PAID", "LATE", "FORFEITED")
    # §3.3: rent_portion = amount - credit_portion.
    assert data["rent_portion_cents"] == data["amount_cents"] - data["credit_portion_cents"], (
        "rent_portion_cents must equal amount_cents - credit_portion_cents"
    )


def assert_maintenance_ticket(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["summary"], str)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in ("OPEN", "APPROVED", "RESOLVED", "REJECTED")


def assert_option_exercise(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["locked_price_snapshot_cents"], int)
    assert isinstance(data["max_credit_cap_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["option_fee_credit_cents"], int)
    assert isinstance(data["net_due_at_closing_cents"], int)
    assert data["status"] in ("PENDING", "SETTLED", "VOIDED")


def assert_mortgage(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["option_exercise_id"], str)
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["monthly_installment_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_maintenance_split_conserved(data: dict, cost_cents: int):
    """§3.5: tenant_share + landlord_share always reconstitutes the full cost exactly."""
    assert data["tenant_share_cents"] + data["landlord_share_cents"] == cost_cents, (
        f"shares {data['tenant_share_cents']} + {data['landlord_share_cents']} "
        f"must sum to cost {cost_cents}"
    )
