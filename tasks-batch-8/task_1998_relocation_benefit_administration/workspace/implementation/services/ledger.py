"""Case cost ledger mutations. Every helper updates the parent case's
total_committed_cents / total_paid_cents / total_released_cents and bumps the
case's version + updated_at (PRD §2.4 child-mutation rule).
"""

from db import DB


def touch_case(case):
    case["updated_at"] = DB.now()
    case["version"] = case.get("version", 0) + 1


def touch_entity(entity):
    entity["updated_at"] = DB.now()
    entity["version"] = entity.get("version", 0) + 1


def commit(case, amount):
    case["total_committed_cents"] = case.get("total_committed_cents", 0) + amount
    touch_case(case)


def release(case, amount):
    case["total_committed_cents"] = case.get("total_committed_cents", 0) - amount
    case["total_released_cents"] = case.get("total_released_cents", 0) + amount
    touch_case(case)


def pay(case, committed_amount, paid_amount):
    """Move committed -> paid; paid may differ from committed (e.g. gross-up, final invoice)."""
    case["total_committed_cents"] = case.get("total_committed_cents", 0) - committed_amount
    case["total_paid_cents"] = case.get("total_paid_cents", 0) + paid_amount
    touch_case(case)


def pay_direct(case, paid_amount):
    """Pay without going through committed (e.g. home-sale settlement)."""
    case["total_paid_cents"] = case.get("total_paid_cents", 0) + paid_amount
    touch_case(case)
