"""Shared route utilities."""

from errors import ApiError
from store import db, public, sort_rows


def require(table, entity_id, error_id):
    row = table.get(entity_id) if isinstance(entity_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def paginate(rows, limit, offset):
    ordered = sort_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], total


def group_active_rule(group_id):
    for rule in db.budget_rules.values():
        if rule["group_id"] == group_id and rule["status"] == "ACTIVE":
            return rule
    return None


def employee_program(employee):
    return db.meal_programs.get(employee["program_id"])


def period_of_order(order):
    return db.benefit_periods.get(order["benefit_period_id"])


def pinned_rule(period):
    return db.budget_rules.get(period.get("budget_rule_id"))
