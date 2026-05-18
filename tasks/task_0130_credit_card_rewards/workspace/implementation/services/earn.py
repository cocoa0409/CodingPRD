"""Earn calculation: calc_points_provisional and calc_points_final.

PRD §3.4 spells out the six-step evaluation order:
  1) category_rate_bps
  2) tier_multiplier_bps
  3) activation_multiplier_bps (always 10000; rotating-quarterly fallback is encoded in step 1)
  4) combined_bps = floor( category_rate_bps * tier_multiplier_bps / 10000 )
  5) points = floor( amount_cents * combined_bps / 10000 )
  6) if lifecycle_state != ACTIVE -> 0
"""
from __future__ import annotations

from datetime import datetime

from constants import BASE_BPS, TIER_MULT_BPS
from store import store
from utils import month_key_utc, parse_iso, quarter_label_for


def _find_active_activation(account_id: str, category_id: str, posted_at: datetime) -> dict | None:
    """Return the QuarterlyActivation row applicable to this (account, category)
    at the given posted_at instant, or None if no active activation covers it.

    Per PRD §3.4: the activation must match quarter_of(posted_at), be in
    ACTIVATED status, and posted_at must lie inside [start, end).
    """
    target_q = quarter_label_for(posted_at)
    for a in store.quarterly_activations.values():
        if a["account_id"] != account_id:
            continue
        if a["category_id"] != category_id:
            continue
        if a["quarter_label"] != target_q:
            continue
        if a["status"] != "ACTIVATED":
            continue
        start = parse_iso(a["activation_window_start"])
        end = parse_iso(a["activation_window_end"])
        if start <= posted_at < end:
            return a
    return None


def compute_points(
    *,
    account: dict,
    category: dict,
    amount_cents: int,
    posted_at: datetime,
    tier_override: str | None = None,
) -> int:
    """Compute points using the six-step formula in PRD §3.4.

    `tier_override` lets calc_points_final substitute the new tier when
    re-rating same-month transactions.
    """
    # Step 6 short-circuit: lifecycle gate (we evaluate at the top to avoid
    # any other work for non-ACTIVE accounts).
    if account["lifecycle_state"] != "ACTIVE":
        return 0

    # Step 1: category rate
    if category["category_type"] == "ROTATING_QUARTERLY":
        active = _find_active_activation(account["id"], category["id"], posted_at)
        if active is None:
            category_rate_bps = BASE_BPS
        else:
            category_rate_bps = int(category["base_rate_bps"])
    else:
        category_rate_bps = int(category["base_rate_bps"])

    # Step 2: tier multiplier
    tier = tier_override if tier_override is not None else account["spending_tier"]
    tier_mult_bps = TIER_MULT_BPS[tier]

    # Step 3: activation multiplier — fixed at 10000 per PRD §3.4 step 3
    # (already baked into step 1 fallback)
    # activation_mult_bps = 10_000  (unused; kept for documentary purposes)

    # Step 4: combined_bps with floor BEFORE applying to dollars
    combined_bps = (category_rate_bps * tier_mult_bps) // 10_000

    # Step 5: points with floor at cents->points conversion
    points = (int(amount_cents) * combined_bps) // 10_000
    return points


def rerate_same_month_transactions(account: dict, new_tier: str) -> list[dict]:
    """Forward-looking backfill: re-rate every POSTED transaction in the current
    calendar month UTC using new_tier. Returns the list of EARN_ADJUST ledger
    entries that should be appended.

    Each affected transaction has its points_final updated. When delta == 0,
    points_final is still updated to equal points_provisional (no ledger entry).

    The caller is responsible for actually appending the ledger entries and
    recomputing the account balance.
    """
    from services.ledger import append_entry  # local import to avoid cycle

    now = store.now()
    current_month = month_key_utc(now)
    aid = account["id"]

    # Walk all POSTED transactions for this account, in posted_at order.
    affected = []
    for t in store.transactions.values():
        if t["account_id"] != aid:
            continue
        if t["status"] != "POSTED":
            continue
        if t["txn_type"] != "PURCHASE":
            continue
        if month_key_utc(parse_iso(t["posted_at"])) != current_month:
            continue
        affected.append(t)

    affected.sort(key=lambda r: (r["posted_at"], r["id"]))

    written = []
    for t in affected:
        category = store.cashback_categories[t["category_id"]]
        posted_at_dt = parse_iso(t["posted_at"])
        new_points = compute_points(
            account=account,
            category=category,
            amount_cents=int(t["amount_cents"]),
            posted_at=posted_at_dt,
            tier_override=new_tier,
        )
        # Invariant: the total ledger contribution for transaction T equals
        # `new_points` after this backfill — i.e. one EARN entry of size
        # points_provisional plus zero or more EARN_ADJUST entries that sum
        # to `new_points - points_provisional`. To support multi-hop tier
        # upgrades within a single post we subtract any EARN_ADJUST rows
        # already present for this transaction so the new row carries only
        # the incremental delta.
        already_adjusted = sum(
            int(e["delta_points"])
            for e in store.points_ledger.values()
            if e["source_entity_type"] == "Transaction"
            and e["source_entity_id"] == t["id"]
            and e["entry_type"] == "EARN_ADJUST"
        )
        target_delta_total = new_points - int(t["points_provisional"])
        delta = target_delta_total - already_adjusted
        t["points_final"] = new_points
        # Refresh transaction metadata (counts as a derived-field mutation).
        from services.touch import touch_versioned
        touch_versioned(t)
        if delta != 0:
            entry = append_entry(
                account_id=aid,
                entry_type="EARN_ADJUST",
                delta_points=delta,
                source_entity_type="Transaction",
                source_entity_id=t["id"],
            )
            written.append(entry)
    return written
