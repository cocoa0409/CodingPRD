"""Reconciliation engine: derived-field recomputation for all entities.

All money is integer cents; no rounding anywhere (PRD §2.4).

Derived fields:
  Account.cleared_balance_cents / available_balance_cents      (PRD §2.10)
  Household.net_worth_cents / projected_net_worth_cents         (PRD §2.10)
  Household.posture                                             (PRD §2.8)
  BudgetCategory.spent_cents / available_cents / envelope_state (PRD §2.11)
  BudgetPeriod.total_allocated_cents
  Goal.funded_cents

Recomputing a derived field counts as a mutation of the owning resource:
updated_at refreshed and version incremented (PRD §2.5).
"""

from db import db, now_ts

ASSET_TYPES = {"DEPOSITORY", "INVESTMENT"}


def touch(rec):
    """Bump updated_at + version (a derived recompute counts as a mutation)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def account_sign(acc):
    return 1 if acc["account_type"] in ASSET_TYPES else -1


def account_transactions(account_id):
    return [t for t in db.transactions.values() if t["account_id"] == account_id]


def recompute_account_balances(acc):
    cleared = acc["opening_balance_cents"]
    available = acc["opening_balance_cents"]
    for t in account_transactions(acc["id"]):
        st = t["status"]
        if st == "REMOVED":
            continue
        if st == "POSTED":
            cleared += t["amount_cents"]
            available += t["amount_cents"]
        elif st == "PENDING":
            available += t["amount_cents"]
    changed = (acc["cleared_balance_cents"] != cleared
               or acc["available_balance_cents"] != available)
    acc["cleared_balance_cents"] = cleared
    acc["available_balance_cents"] = available
    if changed:
        touch(acc)


def recompute_net_worth(household):
    net = 0
    projected = 0
    for acc in db.accounts.values():
        if acc["household_id"] != household["id"]:
            continue
        if acc["status"] != "LINKED":
            continue
        sign = account_sign(acc)
        net += sign * acc["cleared_balance_cents"]
        projected += sign * acc["available_balance_cents"]
    changed = (household["net_worth_cents"] != net
               or household["projected_net_worth_cents"] != projected)
    household["net_worth_cents"] = net
    household["projected_net_worth_cents"] = projected
    if changed:
        touch(household)


def category_spent(cat):
    total = 0
    for t in db.transactions.values():
        if (t.get("budget_category_id") == cat["id"]
                and t.get("posted_period_id") == cat["budget_period_id"]
                and t["status"] == "POSTED"
                and t["amount_cents"] < 0):
            total += -t["amount_cents"]
    return total


def category_contributions(cat):
    total = 0
    for gc in db.goal_contributions.values():
        if gc["reversed"]:
            continue
        goal = db.goals.get(gc["goal_id"])
        if goal is not None and goal["funding_category_id"] == cat["id"]:
            total += gc["amount_cents"]
    return total


def recompute_category(cat):
    spent = category_spent(cat)
    contrib = category_contributions(cat)
    available = cat["allocated_cents"] + cat["rollover_in_cents"] - spent - contrib
    if available < 0:
        state = "OVER"
    elif spent > 0 or contrib > 0:
        state = "DRAWN"
    else:
        state = "FUNDED"
    changed = (cat["spent_cents"] != spent
               or cat["available_cents"] != available
               or cat["envelope_state"] != state)
    cat["spent_cents"] = spent
    cat["available_cents"] = available
    cat["envelope_state"] = state
    if changed:
        touch(cat)


def recompute_period_total(period):
    total = 0
    for c in db.budget_categories.values():
        if c["budget_period_id"] == period["id"]:
            total += c["allocated_cents"]
    changed = period["total_allocated_cents"] != total
    period["total_allocated_cents"] = total
    if changed:
        touch(period)


def recompute_goal_funded(goal):
    funded = 0
    for gc in db.goal_contributions.values():
        if gc["goal_id"] == goal["id"] and not gc["reversed"]:
            funded += gc["amount_cents"]
    changed = goal["funded_cents"] != funded
    goal["funded_cents"] = funded
    if changed:
        touch(goal)


def recompute_posture(household):
    """PRD §2.8: FROZEN dominates; else OVERSPENT if any current-period category
    is OVER; else HEALTHY."""
    if household["frozen_by_owner"]:
        posture = "FROZEN"
    else:
        posture = "HEALTHY"
        cur = household.get("current_period_id")
        if cur is not None:
            for c in db.budget_categories.values():
                if c["budget_period_id"] == cur and c["envelope_state"] == "OVER":
                    posture = "OVERSPENT"
                    break
    changed = household["posture"] != posture
    household["posture"] = posture
    if changed:
        touch(household)
