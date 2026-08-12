"""Inventory buckets, the replenishment flag and its transfer cascade (PRD 3.2)."""

from core.constants import REORDER_POINT_PAIRS
from core.store import db, order_key


def shop_bucket(sku_id):
    for bucket in db.inventory_buckets.values():
        if bucket["sku_id"] == sku_id and bucket["location_kind"] == "SHOP":
            return bucket
    return None


def van_bucket(farrier_id, sku_id):
    for bucket in db.inventory_buckets.values():
        if (
            bucket["sku_id"] == sku_id
            and bucket["location_kind"] == "VAN"
            and bucket["farrier_id"] == farrier_id
        ):
            return bucket
    return None


def _mint_bucket(location_kind, farrier_id, sku_id):
    # The flag is recomputed on every write INCLUDING creation, so a bucket
    # holding zero available pairs is born REPLENISHMENT_FLAGGED.
    return db.mint(
        "inventory_buckets",
        {
            "location_kind": location_kind,
            "farrier_id": farrier_id,
            "sku_id": sku_id,
            "on_hand_pairs": 0,
            "available_pairs": 0,
            "reserved_pairs": 0,
            "replenishment_flag": 0 <= REORDER_POINT_PAIRS,
        },
    )


def mint_buckets_for_farrier(farrier):
    """Creating a farrier mints one VAN bucket for each existing SKU."""
    for sku in db.all("shoe_skus"):
        _mint_bucket("VAN", farrier["id"], sku["id"])


def mint_buckets_for_sku(sku):
    """Creating a SKU mints its one SHOP bucket plus the per-farrier VAN buckets.

    # Adjudication of friction 3: a VAN bucket is minted per EXISTING farrier
    # row regardless of status -- not only for ACTIVE farriers.  The narrative
    # that owns the rule (section 3.2) says "one VAN bucket per existing
    # farrier", and minting for every row keeps every declared behaviour
    # reachable: a farrier who is INACTIVE or DECERTIFIED today can be
    # reactivated or recertified tomorrow and finds its stock already in place,
    # whereas the ACTIVE-only reading would leave that farrier permanently
    # without a bucket for the SKU and make its attachments unsatisfiable.
    """
    _mint_bucket("SHOP", None, sku["id"])
    for farrier in db.all("farriers"):
        _mint_bucket("VAN", farrier["id"], sku["id"])


def recompute_flag(bucket):
    """The threshold axis: flagged exactly while available_pairs <= 2.

    Returns True when the flag flipped from true to false in this call.
    """
    before = bucket["replenishment_flag"]
    after = bucket["available_pairs"] <= REORDER_POINT_PAIRS
    bucket["replenishment_flag"] = after
    return before and not after


def cancel_inbound_requested_transfers(bucket):
    """A cleared shortage cancels every transfer still REQUESTED into the bucket."""
    rows = [
        t
        for t in db.stock_transfers.values()
        if t["to_bucket_id"] == bucket["id"] and t["status"] == "REQUESTED"
    ]
    for transfer in sorted(rows, key=order_key):
        transfer["status"] = "CANCELLED"
        db.touch(transfer)


def move_bucket(bucket, on_hand=0, available=0, reserved=0):
    """Apply signed deltas to one bucket, recompute its flag and cascade."""
    bucket["on_hand_pairs"] += on_hand
    bucket["available_pairs"] += available
    bucket["reserved_pairs"] += reserved
    flipped_clear = recompute_flag(bucket)
    db.touch(bucket)
    if flipped_clear:
        cancel_inbound_requested_transfers(bucket)
    return bucket
