"""Calculation 4: referral_attributed_share_cents, the revenue-share ledger and
the feed source accrual roll-up."""

from decimal import Decimal

import db
from services import enums


def commission_provisional(partner, gross_revenue_cents):
    """provisional_at_conversion: a 10% holdback on percentage deals."""
    if partner["payout_model"] == "FLAT_BOUNTY":
        return int(partner["bounty_cents"])
    gross = Decimal(gross_revenue_cents)
    return int(
        db.round_money(gross * partner["rev_share_pct"] * enums.PROVISIONAL_HAIRCUT, 0)
    )


def commission_settled(partner, settled_gross_revenue_cents):
    """settled_at_settlement: the holdback is released."""
    if partner["payout_model"] == "FLAT_BOUNTY":
        return int(partner["bounty_cents"])
    gross = Decimal(settled_gross_revenue_cents)
    return int(db.round_money(gross * partner["rev_share_pct"], 0))


def feed_source_share(commission_cents, feed_source):
    return int(
        db.round_money(
            Decimal(commission_cents) * feed_source["referral_revenue_share_pct"], 0
        )
    )


def post_entry(placement, move, entry_type, amount_cents):
    entry = db.base_record(versioned=False)
    entry.update(
        {
            "placement_id": placement["id"],
            "move_id": move["id"],
            "feed_source_id": move["feed_source_id"],
            "entry_type": entry_type,
            "amount_cents": int(amount_cents),
            "posted_at": db.now_iso(),
        }
    )
    db.db.ledger[entry["id"]] = entry
    return entry


def recompute_feed_accrual(feed_source):
    """Round-then-sum over the feed's converted and settled placements."""
    total = 0
    for placement in db.db.placements.values():
        if placement["placement_status"] not in enums.PLACEMENT_ACCRUING:
            continue
        move = db.db.moves.get(placement["move_id"])
        if move is None or move["feed_source_id"] != feed_source["id"]:
            continue
        total += int(placement["feed_source_share_cents"])
    if feed_source["accrued_share_cents"] != total:
        feed_source["accrued_share_cents"] = total
        db.touch(feed_source)
    return total


def ledger_balance(placement_id):
    return sum(
        e["amount_cents"]
        for e in db.db.ledger.values()
        if e["placement_id"] == placement_id
    )
