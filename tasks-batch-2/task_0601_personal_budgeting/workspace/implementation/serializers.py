"""Resource serializers — produce the public JSON shape for each entity.

Common fields (PRD §2.5): id, created_at, updated_at, version on every entity
except GoalContribution (append-only: id + created_at only).
"""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def household(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "base_currency": rec["base_currency"],
        "owner_member_id": rec["owner_member_id"],
        "current_period_id": rec["current_period_id"],
        "posture": rec["posture"],
        "net_worth_cents": rec["net_worth_cents"],
        "projected_net_worth_cents": rec["projected_net_worth_cents"],
        "frozen_by_owner": rec["frozen_by_owner"],
    })
    return out


def member(rec):
    out = _common(rec)
    out.update({
        "household_id": rec["household_id"],
        "email": rec["email"],
        "display_name": rec["display_name"],
        "role": rec["role"],
    })
    return out


def account(rec):
    out = _common(rec)
    out.update({
        "household_id": rec["household_id"],
        "institution_name": rec["institution_name"],
        "account_type": rec["account_type"],
        "cleared_balance_cents": rec["cleared_balance_cents"],
        "available_balance_cents": rec["available_balance_cents"],
        "opening_balance_cents": rec["opening_balance_cents"],
        "status": rec["status"],
    })
    return out


def transaction(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "budget_category_id": rec["budget_category_id"],
        "amount_cents": rec["amount_cents"],
        "merchant_name": rec["merchant_name"],
        "posted_period_id": rec["posted_period_id"],
        "status": rec["status"],
        "state": rec["status"],
    })
    return out


def category_rule(rec):
    out = _common(rec)
    out.update({
        "household_id": rec["household_id"],
        "match_substring": rec["match_substring"],
        "budget_category_id": rec["budget_category_id"],
        "priority": rec["priority"],
        "enabled": rec["enabled"],
    })
    return out


def budget_period(rec):
    out = _common(rec)
    out.update({
        "household_id": rec["household_id"],
        "month": rec["month"],
        "status": rec["status"],
        "income_expected_cents": rec["income_expected_cents"],
        "total_allocated_cents": rec["total_allocated_cents"],
    })
    return out


def budget_category(rec):
    out = _common(rec)
    out.update({
        "budget_period_id": rec["budget_period_id"],
        "household_id": rec["household_id"],
        "name": rec["name"],
        "allocated_cents": rec["allocated_cents"],
        "rollover_in_cents": rec["rollover_in_cents"],
        "spent_cents": rec["spent_cents"],
        "available_cents": rec["available_cents"],
        "envelope_state": rec["envelope_state"],
        "rollover_enabled": rec["rollover_enabled"],
    })
    return out


def goal(rec):
    out = _common(rec)
    out.update({
        "household_id": rec["household_id"],
        "name": rec["name"],
        "target_cents": rec["target_cents"],
        "funded_cents": rec["funded_cents"],
        "funding_category_id": rec["funding_category_id"],
        "status": rec["status"],
    })
    return out


def goal_contribution(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "goal_id": rec["goal_id"],
        "amount_cents": rec["amount_cents"],
        "reversed": rec["reversed"],
    }


def recurring_bill(rec):
    out = _common(rec)
    out.update({
        "household_id": rec["household_id"],
        "payee": rec["payee"],
        "amount_cents": rec["amount_cents"],
        "day_of_month": rec["day_of_month"],
        "funding_category_id": rec["funding_category_id"],
        "status": rec["status"],
    })
    return out
