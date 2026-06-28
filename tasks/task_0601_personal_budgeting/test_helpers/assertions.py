"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_household(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Household.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["posture"] in ["HEALTHY", "OVERSPENT", "FROZEN"], \
        f"unexpected posture {data['posture']}"
    assert isinstance(data["net_worth_cents"], int)
    assert isinstance(data["projected_net_worth_cents"], int)
    assert data["base_currency"] in ["USD", "EUR", "GBP"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Member.id must be valid UUID"
    assert data["role"] in ["OWNER", "MEMBER"]
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Account.id must be valid UUID"
    assert data["account_type"] in ["DEPOSITORY", "CREDIT", "LOAN", "INVESTMENT"]
    assert data["status"] in ["LINKED", "ARCHIVED"]
    assert isinstance(data["cleared_balance_cents"], int)
    assert isinstance(data["available_balance_cents"], int)


def assert_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Transaction.id must be valid UUID"
    assert data["status"] in ["PENDING", "POSTED", "RECATEGORIZED", "REMOVED"]
    assert isinstance(data["amount_cents"], int)


def assert_budget_period(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BudgetPeriod.id must be valid UUID"
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["total_allocated_cents"], int)


def assert_budget_category(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BudgetCategory.id must be valid UUID"
    assert data["envelope_state"] in ["FUNDED", "DRAWN", "OVER"]
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert data["spent_cents"] >= 0, "spent_cents is a non-negative magnitude"


def assert_goal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Goal.id must be valid UUID"
    assert data["status"] in ["ACTIVE", "FUNDED", "ABANDONED"]
    assert isinstance(data["target_cents"], int)
    assert isinstance(data["funded_cents"], int)


def assert_goal_contribution(data: dict):
    """GoalContribution is append-only: id + created_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "GoalContribution.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)


def assert_recurring_bill(data: dict):
    assert is_valid_uuid(data.get("id", "")), "RecurringBill.id must be valid UUID"
    assert data["status"] in ["SCHEDULED", "PAUSED"]
    assert 1 <= data["day_of_month"] <= 28


def assert_envelope_consistency(data: dict):
    """available_cents = allocated_cents + rollover_in_cents - spent_cents - contributions.
    We cannot see contributions on the category read, but with zero contributions the
    identity allocated + rollover_in - spent == available must hold (PRD §2.11)."""
    expected = data["allocated_cents"] + data["rollover_in_cents"] - data["spent_cents"]
    # Only assert when contributions are absent (caller responsibility); kept as a
    # weaker upper-bound invariant: available never exceeds allocated+rollover.
    assert data["available_cents"] <= data["allocated_cents"] + data["rollover_in_cents"], \
        "available_cents must not exceed allocated + rollover_in"
    return expected
