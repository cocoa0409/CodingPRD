"""Purchase classification and the two independently floored earning legs (PRD 3.3)."""

from decimal import Decimal

from core import DB, dec, floor_int, parse_dt
from svc_pricing import EARN_MULTIPLIER

ONE = Decimal(1)


def fallback_category():
    rows = [c for c in DB["merchant_categories"].values() if c["is_fallback"]]
    return rows[0] if rows else None


def category_by_mcc(mcc_code):
    for row in DB["merchant_categories"].values():
        if row["mcc_code"] == mcc_code:
            return row
    return None


def classify(mcc_code):
    """Returns (merchant_category_id, classification_source, base_multiplier)."""
    mapped = category_by_mcc(mcc_code)
    if mapped is not None:
        return mapped["id"], "MAPPED", dec(mapped["base_multiplier"])
    fallback = fallback_category()
    if fallback is not None:
        return fallback["id"], "FALLBACK", dec(fallback["base_multiplier"])
    return None, "FALLBACK", ONE


def active_rotation_for(category_id, posted_at):
    """At most one ACTIVE rotation can cover a category at an instant."""
    if category_id is None:
        return None
    instant = parse_dt(posted_at)
    for rotation in DB["rotations"].values():
        if rotation["merchant_category_id"] != category_id:
            continue
        if rotation["status"] != "ACTIVE":
            continue
        start = parse_dt(rotation["window_start"])
        end = parse_dt(rotation["window_end"])
        if start <= instant < end:
            return rotation
    return None


def prior_rotation_spend(account_id, rotation_id, transaction):
    """Per-account cumulative rotation spend from earlier POSTED purchases only."""
    key = (transaction["created_at"], transaction["_seq"])
    total = 0
    earlier = [
        t
        for t in DB["transactions"].values()
        if t["account_id"] == account_id
        and t.get("rotation_id") == rotation_id
        and t["status"] == "POSTED"
        and t["id"] != transaction["id"]
    ]
    earlier.sort(key=lambda t: (t["created_at"], t["_seq"]))
    for row in earlier:
        if (row["created_at"], row["_seq"]) < key:
            total += row["rotation_eligible_cents"]
    return total


def award(transaction, account):
    """Populate the classification, both earning legs and the total on the row."""
    product_multiplier = EARN_MULTIPLIER[account["card_product_code"]]
    category_id, source, base_multiplier = classify(transaction["mcc_code"])
    transaction["merchant_category_id"] = category_id
    transaction["classification_source"] = source

    billable_dollars = transaction["amount_cents"] // 100
    transaction["base_points"] = floor_int(
        dec(billable_dollars) * base_multiplier * product_multiplier
    )

    rotation = active_rotation_for(category_id, transaction["posted_at"])
    if rotation is None:
        transaction["rotation_id"] = None
        transaction["rotation_eligible_cents"] = 0
        transaction["bonus_points"] = 0
    else:
        transaction["rotation_id"] = rotation["id"]
        prior = prior_rotation_spend(account["id"], rotation["id"], transaction)
        headroom = rotation["capped_spend_cents"] - prior
        if headroom < 0:
            headroom = 0
        eligible = min(transaction["amount_cents"], headroom)
        transaction["rotation_eligible_cents"] = eligible
        eligible_dollars = eligible // 100
        incremental = dec(rotation["bonus_multiplier"]) - ONE
        transaction["bonus_points"] = floor_int(
            dec(eligible_dollars) * incremental * product_multiplier
        )

    transaction["total_points_earned"] = transaction["base_points"] + transaction["bonus_points"]
    return transaction
