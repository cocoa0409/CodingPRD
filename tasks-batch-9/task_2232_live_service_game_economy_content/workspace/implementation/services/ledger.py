"""Append-only economy ledger and its fan-out (PRD 2.8)."""
import db
from response import touch
from services import calc


def append_entry(
    account,
    direction,
    amount_minor,
    source_kind,
    season_id,
    purchase_id=None,
    reversal_of_entry_id=None,
):
    """L1 append, then the L2 (account) and L3/L4 (season) cascade levels."""
    entry = db.insert(
        db.db.ledger,
        {
            "currency_account_id": account["id"],
            "season_id": season_id,
            "purchase_id": purchase_id,
            "direction": direction,
            "amount_minor": amount_minor,
            "source_kind": source_kind,
            "occurred_at": db.now(),
            "reversal_of_entry_id": reversal_of_entry_id,
        },
        common_fields=False,
    )
    apply_to_account(account, direction, amount_minor)
    apply_to_season(season_id, direction, amount_minor)
    return entry


def apply_to_account(account, direction, amount_minor):
    if direction == "FAUCET":
        account["lifetime_faucet_minor"] += amount_minor
    else:
        account["lifetime_sink_minor"] += amount_minor
    account["balance_minor"] = max(
        0, account["lifetime_faucet_minor"] - account["lifetime_sink_minor"]
    )
    touch(account)


def apply_to_season(season_id, direction, amount_minor):
    season = db.db.seasons.get(season_id)
    if season is None:
        return
    if direction == "FAUCET":
        season["gross_faucet_minor"] += amount_minor
    else:
        season["gross_sink_minor"] += amount_minor
    calc.refresh_lifetime_ratio(season)
    touch(season)


def entries_for_purchase(purchase_id, source_kind):
    rows = [
        entry
        for entry in db.db.ledger.values()
        if entry["purchase_id"] == purchase_id and entry["source_kind"] == source_kind
    ]
    return db.ordered(rows)
