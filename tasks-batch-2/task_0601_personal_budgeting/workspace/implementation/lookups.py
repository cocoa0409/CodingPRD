"""Path-resource resolution helpers. Raise ERR_NOT_FOUND when a path id is absent.

Path identifiers are validated left-to-right (PRD §2.6).
"""

import errors
from db import db


def get_household(household_id):
    h = db.households.get(household_id)
    if h is None:
        raise errors.not_found("Household not found")
    return h


def get_account(account_id):
    a = db.accounts.get(account_id)
    if a is None:
        raise errors.not_found("Account not found")
    return a


def get_transaction(txn_id):
    t = db.transactions.get(txn_id)
    if t is None:
        raise errors.not_found("Transaction not found")
    return t


def get_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise errors.not_found("Member not found")
    return m


def get_period(period_id):
    p = db.budget_periods.get(period_id)
    if p is None:
        raise errors.not_found("Budget period not found")
    return p


def get_category(cat_id):
    c = db.budget_categories.get(cat_id)
    if c is None:
        raise errors.not_found("Budget category not found")
    return c


def get_rule(rule_id):
    r = db.category_rules.get(rule_id)
    if r is None:
        raise errors.not_found("Category rule not found")
    return r


def get_goal(goal_id):
    g = db.goals.get(goal_id)
    if g is None:
        raise errors.not_found("Goal not found")
    return g


def get_contribution(c_id):
    c = db.goal_contributions.get(c_id)
    if c is None:
        raise errors.not_found("Goal contribution not found")
    return c


def get_bill(bill_id):
    b = db.recurring_bills.get(bill_id)
    if b is None:
        raise errors.not_found("Recurring bill not found")
    return b


def household_of_account(acc):
    return get_household(acc["household_id"])
