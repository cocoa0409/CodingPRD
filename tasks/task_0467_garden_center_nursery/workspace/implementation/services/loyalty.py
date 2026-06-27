"""Loyalty ledger + account derived-field reconciliation (PRD §3.5)."""
from db import db, base_ledger, now_iso


def append_event(account, event_type, points_delta, source_kind, source_ref_id):
    """Append an append-only LoyaltyEvent and recompute the account."""
    ev = base_ledger()
    ev.update({
        "account_id": account["id"],
        "event_type": event_type,            # ACCRUAL | REDEMPTION | REVERSAL
        "points_delta": points_delta,        # signed
        "source_kind": source_kind,          # ORDER | WARRANTY_CLAIM
        "source_ref_id": source_ref_id,
        "recorded_at": now_iso(),
    })
    db.loyalty_events[ev["id"]] = ev
    recompute_account_loyalty(account)
    return ev


def recompute_account_loyalty(account):
    """Derive lifetime_points, points_balance, loyalty_tier from ledger.

    lifetime_points = running sum of all deltas, floored at 0.
    points_balance = lifetime accruals - lifetime redemptions, floored at 0.
                     (REVERSAL deltas are negative -> reduce balance like redemptions
                      do; we sum all signed deltas for the balance, floored at 0.)
    loyalty_tier   = GOLD iff lifetime_points >= nursery.gold_tier_threshold_points.
    """
    events = [e for e in db.loyalty_events.values()
              if e["account_id"] == account["id"]]

    total = sum(e["points_delta"] for e in events)
    lifetime = max(0, total)

    # points_balance: accruals (positive ACCRUAL) minus everything spent/clawed.
    # All signed deltas summed give the redeemable balance; never below 0.
    balance = max(0, total)

    account["lifetime_points"] = lifetime
    account["points_balance"] = balance

    nursery = db.nurseries.get(account["nursery_id"])
    threshold = nursery["gold_tier_threshold_points"] if nursery else 1000
    account["loyalty_tier"] = "GOLD" if lifetime >= threshold else "STANDARD"
