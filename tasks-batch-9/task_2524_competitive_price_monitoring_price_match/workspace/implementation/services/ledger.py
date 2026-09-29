"""The two conserved per-store daily ledgers (PRD 2.12, 3.9, 3.10).

Both quantities are derived aggregates recomputed from their underlying rows,
never incrementally patched counters.
"""
import clock
import db
from util import utc_date


def batch_item_count(batch):
    """reserved_item_count plus the queued entries; 0 once cancelled (PRD 3.10)."""
    if batch["status"] == "CANCELLED":
        return 0
    return batch["reserved_item_count"] + len(batch["queued_order_ids"])


def label_slots_used_today(store):
    """Sum of item_count over the store's live batches whose window_start is today."""
    today = utc_date(clock.now())
    total = 0
    for batch in db.batches.values():
        if batch["store_id"] != store["id"]:
            continue
        if batch["status"] not in ("SCHEDULED", "PRINTING", "COMPLETED"):
            continue
        if utc_date(batch["window_start"]) != today:
            continue
        total += batch_item_count(batch)
    return total


def label_slots_remaining_today(store):
    return store["label_printer_capacity_per_day"] - label_slots_used_today(store)


def active_policy_for_market(market_id):
    """A market holds at most one ACTIVE price match policy."""
    live = [p for p in db.ordered(db.policies)
            if p["market_id"] == market_id and p["status"] == "ACTIVE"]
    return live[0] if live else None


def override_budget_used_cents(store):
    """DEBIT rows minus CREDIT rows on the logical clock's current UTC date."""
    today = utc_date(clock.now())
    used = 0
    for log in db.override_logs.values():
        claim = db.claims.get(log["claim_id"])
        if claim is None or claim["store_id"] != store["id"]:
            continue
        if utc_date(log["created_at"]) != today:
            continue
        if log["direction"] == "DEBIT":
            used += log["approved_discount_cents"]
        else:
            used -= log["approved_discount_cents"]
    return used


def override_budget_remaining_cents(store):
    policy = active_policy_for_market(store["market_id"])
    if policy is None:
        return None
    return policy["daily_override_budget_cents"] - override_budget_used_cents(store)
