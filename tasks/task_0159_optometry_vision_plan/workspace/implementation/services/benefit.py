"""Benefit pool / eligibility helpers shared across lab-order and claim flows."""
from db import db


def pools_for(eligibility_id):
    return [p for p in db.benefit_pools.values()
            if p["eligibility_id"] == eligibility_id]


def pool_of_type(eligibility_id, pool_type):
    for p in db.benefit_pools.values():
        if p["eligibility_id"] == eligibility_id and p["pool_type"] == pool_type:
            return p
    return None


def recompute_pool_remaining(pool):
    """remaining = allotted - consumed, never negative."""
    pool["remaining_cents"] = max(0, pool["allotted_cents"] - pool["consumed_cents"])
    return pool


def is_in_period(elig, current_date):
    """clock date between benefit_period_start and benefit_period_end inclusive."""
    import clock
    start = clock.parse_date(elig["benefit_period_start"])
    end = clock.parse_date(elig["benefit_period_end"])
    return start <= current_date <= end
