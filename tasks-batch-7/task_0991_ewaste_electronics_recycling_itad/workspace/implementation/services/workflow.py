"""Shared workflow side effects: custody trail, ledger posting, cascades."""

import db
import utils
from services import calculations as calc


def manifest_items(manifest_id):
    return [i for i in db.items.values() if i["manifest_id"] == manifest_id]


def manifest_settlements(manifest_id):
    return [s for s in db.settlements.values() if s["manifest_id"] == manifest_id]


def write_custody(subject_type, subject_id, event_type, actor_id,
                  from_location=None, to_location=None):
    event = {
        "id": utils.new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "from_location": from_location,
        "to_location": to_location,
        "actor_id": actor_id,
    }
    utils.stamp_append_only(event)
    db.custody_events[event["id"]] = event
    return event


def post_ledger(account, settlement_id, entry_type, amount_cents):
    """Append a ledger entry and move the account's running balance."""
    account["credit_balance_cents"] += amount_cents
    entry = {
        "id": utils.new_id(),
        "account_id": account["id"],
        "settlement_id": settlement_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": account["credit_balance_cents"],
    }
    utils.stamp_append_only(entry)
    db.ledger_entries[entry["id"]] = entry
    return entry


def recompute_batch_totals(batch):
    contained = [db.items[iid] for iid in batch["item_ids"] if iid in db.items]
    batch["gross_weight_kg"] = sum(
        (i["weight_kg"] for i in contained), calc.Decimal("0")
    )
    batch["item_count"] = len(contained)


def complete_item(item, account, actor_id=None, write_item_custody=False):
    """Item -> COMPLETE: diversion accumulates and may upgrade the tier
    (PRD §3.1). Caller bumps the item/account version once per operation."""
    item["processing_status"] = "COMPLETE"
    item["recycle_batch_id"] = None  # set only while BATCHED/DOWNSTREAM
    account["lifetime_diverted_kg"] += item["weight_kg"]
    calc.apply_tier_threshold(account)
    if write_item_custody:
        write_custody("ITEM", item["id"], "PROCESSED", actor_id)


def recompute_quote_open(manifest):
    """Return cascade: re-run the QUOTE variant on the manifest's QUOTE_OPEN
    settlement, bumping that settlement's version."""
    for s in manifest_settlements(manifest["id"]):
        if s["status"] == "QUOTE_OPEN":
            figures = calc.compute_settlement_figures(
                manifest, manifest_items(manifest["id"]), "QUOTE"
            )
            s.update(figures)
            utils.touch(s)
            return s
    return None
