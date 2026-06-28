"""Payload factories — one per entity, input fields only."""


def create_household_payload(**overrides) -> dict:
    """Input fields for POST /households (PRD §3.1).
    base_currency is optional (defaults to USD)."""
    defaults = {
        "name": "Test Household",
        "owner_email": "owner@example.com",
        "owner_display_name": "Owner",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """Input fields for POST /households/{id}/members."""
    defaults = {
        "email": "member@example.com",
        "display_name": "Member",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    """Input fields for POST /households/{id}/accounts.
    opening_balance_cents optional (defaults to 0)."""
    defaults = {
        "institution_name": "Test Bank",
        "account_type": "DEPOSITORY",
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(**overrides) -> dict:
    """Input fields for POST /accounts/{id}/transactions.
    budget_category_id optional."""
    defaults = {
        "amount_cents": -1000,
        "merchant_name": "Test Merchant",
    }
    defaults.update(overrides)
    return defaults


def create_category_rule_payload(**overrides) -> dict:
    """Input fields for POST /households/{id}/category-rules.
    enabled optional (defaults to true)."""
    defaults = {
        "match_substring": "test",
        "budget_category_id": None,
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_budget_period_payload(**overrides) -> dict:
    """Input fields for POST /households/{id}/budget-periods.
    income_expected_cents optional (defaults to 0)."""
    defaults = {
        "month": "2026-01",
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    """Input fields for POST .../categories.
    allocated_cents and rollover_enabled optional."""
    defaults = {
        "name": "Test Category",
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    """Input fields for POST /households/{id}/goals."""
    defaults = {
        "name": "Test Goal",
        "target_cents": 10000,
        "funding_category_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_recurring_bill_payload(**overrides) -> dict:
    """Input fields for POST /households/{id}/recurring-bills."""
    defaults = {
        "payee": "Test Payee",
        "amount_cents": 1000,
        "day_of_month": 1,
        "funding_category_id": None,
    }
    defaults.update(overrides)
    return defaults
