"""calculations.effective_return_policy_resolution (PRD 3.7)."""

from datetime import timedelta

import clock
from db import db


def candidate_policies(category_code, customer_profile_id):
    """Rows governing this category, live on the clock, for this shopper."""
    now = clock.now()
    candidates = []
    for policy in db.policies.values():
        if policy["category_code"] != category_code:
            continue
        if policy["effective_from"] > now:
            continue
        if policy["effective_to"] is not None and policy["effective_to"] < now:
            continue
        if policy["scope"] == "CUSTOMER_OVERRIDE":
            if policy["customer_profile_id"] != customer_profile_id:
                continue
        candidates.append(policy)
    return candidates


def _rank_key(policy):
    """Overrides outrank defaults, then later effective_from, then later created_at."""
    return (
        1 if policy["scope"] == "CUSTOMER_OVERRIDE" else 0,
        policy["effective_from"],
        policy["created_at"],
        policy["_seq"],
    )


def resolve_effective_policy(category_code, customer_profile_id):
    candidates = candidate_policies(category_code, customer_profile_id)
    if not candidates:
        return None
    return max(candidates, key=_rank_key)


def return_deadline_at(delivered_at, effective_window_days):
    return delivered_at + timedelta(days=effective_window_days)
