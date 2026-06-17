"""Helpers for the Job ledger and bound-estimate-derived material sizing."""
from db import db
from services import calculations as calc


def effective_shingle_squares(job):
    """Effective shingle squares for the job's bound estimate plus APPLIED
    change-order extra squares (PRD §3.4 / §3.8).
    """
    bound_id = job.get("bound_estimate_id")
    base = 0.0
    if bound_id:
        for li in db.line_items.values():
            if li["estimate_id"] == bound_id and li["trade"] == "SHINGLE":
                base += li["squares"]
    extra = 0.0
    for co in db.change_orders.values():
        if co["job_id"] == job["id"] and co["status"] == "APPLIED":
            extra += co.get("extra_shingle_squares", 0) or 0
    return base + extra


def recompute_remaining(job):
    """remaining_billable = max(0, contract_value - disbursed_gross)."""
    job["remaining_billable_cents"] = max(
        0, job["contract_value_cents"] - job["disbursed_gross_cents"]
    )
