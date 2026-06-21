"""Entity assertions and domain invariant checkers for the Renters Insurance API."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_policyholder(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["mailing_address"], str)


def assert_bundle(data: dict):
    _assert_common(data)
    assert isinstance(data["policyholder_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["active_member_count"], int)
    assert isinstance(data["discount_active"], bool)
    assert data["status"] in ("FORMING", "ACTIVE", "DISSOLVED")


def assert_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["policyholder_id"], str)
    assert isinstance(data["insured_address"], str)
    assert data["territory_code"] in ("HIGH", "STANDARD", "LOW")
    assert data["pp_valuation_method"] in ("RCV", "ACV")
    assert data["billing_mode"] in ("ANNUAL", "MONTHLY")
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["annual_premium_cents"], int)
    assert isinstance(data["reinstatement_count"], int)
    assert data["status"] in ("QUOTED", "ACTIVE", "LAPSED", "CANCELLED", "EXPIRED")


def assert_coverage_line(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert data["coverage_type"] in ("PERSONAL_PROPERTY", "LIABILITY", "LOSS_OF_USE")
    assert isinstance(data["limit_cents"], int) and data["limit_cents"] > 0
    assert isinstance(data["settled_cents"], int)
    assert isinstance(data["remaining_limit_cents"], int)
    assert data["status"] in ("OPEN", "EXHAUSTED", "SUSPENDED")
    assert_coverage_line_invariant(data)


def assert_coverage_line_invariant(data: dict):
    """PRD §3.6: limit_cents == remaining_limit_cents + settled_cents, and
    remaining_limit_cents never drops below zero."""
    assert data["remaining_limit_cents"] >= 0, "remaining_limit_cents must not be negative"
    assert (
        data["limit_cents"] == data["remaining_limit_cents"] + data["settled_cents"]
    ), (
        f"limit conservation violated: {data['limit_cents']} != "
        f"{data['remaining_limit_cents']} + {data['settled_cents']}"
    )


def assert_scheduled_item(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["appraised_value_cents"], int) and data["appraised_value_cents"] > 0
    assert isinstance(data["deductible_waived"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REMOVED")


def assert_additional_insured(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["party_name"], str)
    assert data["interest_type"] in ("LANDLORD", "PROPERTY_MANAGER")
    assert isinstance(data["notify_email"], str)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_premium_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert data["status"] in ("OPEN", "PAID", "OVERDUE")
    assert_invoice_balance_invariant(data)


def assert_invoice_balance_invariant(data: dict):
    """PRD §3.3: balance_due_cents == amount_cents - paid_cents."""
    assert (
        data["balance_due_cents"] == data["amount_cents"] - data["paid_cents"]
    ), (
        f"balance invariant violated: {data['balance_due_cents']} != "
        f"{data['amount_cents']} - {data['paid_cents']}"
    )


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "ACH", "CHECK")
    assert data["status"] in ("CLEARED", "VOIDED")


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_id"], str)
    assert data["loss_type"] in ("PERSONAL_PROPERTY", "LIABILITY", "LOSS_OF_USE")
    assert isinstance(data["covered_loss_cents"], int)
    assert isinstance(data["deductible_applied_cents"], int)
    assert isinstance(data["settlement_cents"], int)
    assert isinstance(data["appeal_count"], int)
    assert data["status"] in (
        "FILED",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "SETTLED",
        "SUSPENDED",
    )


def assert_claim_item(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["coverage_line_id"], str)
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] > 0
    assert isinstance(data["covered_item_cents"], int)
