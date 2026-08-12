"""The cyclic life of a shoe reservation (PRD 3.5) and the van-stock rung."""

from core.errors import ApiError
from core.store import db, order_key

from .inventory import move_bucket, van_bucket
from .rollups import shoe_pairs_required


def reservations_of(appointment, statuses=None):
    rows = [
        r
        for r in db.shoe_reservations.values()
        if r["appointment_id"] == appointment["id"]
        and (statuses is None or r["status"] in statuses)
    ]
    rows.sort(key=order_key)
    return rows


def release_reservations(appointment):
    """RESERVED -> RELEASED: available rises, reserved falls, on_hand untouched."""
    for reservation in reservations_of(appointment, ("RESERVED",)):
        bucket = db.get("inventory_buckets", reservation["bucket_id"])
        reservation["status"] = "RELEASED"
        db.touch(reservation)
        if bucket is not None:
            move_bucket(bucket, available=reservation["pairs"], reserved=-reservation["pairs"])


def commit_reservations(appointment):
    """RESERVED -> COMMITTED: on_hand and reserved fall, available untouched."""
    for reservation in reservations_of(appointment, ("RESERVED",)):
        bucket = db.get("inventory_buckets", reservation["bucket_id"])
        reservation["status"] = "COMMITTED"
        db.touch(reservation)
        if bucket is not None:
            move_bucket(bucket, on_hand=-reservation["pairs"], reserved=-reservation["pairs"])


def check_van_stock_for_attach(appointment, farrier_id):
    """Rung 51 -- every SKU on the visit must be covered by the farrier's van."""
    required = shoe_pairs_required(appointment)
    for sku_id, pairs in required.items():
        bucket = van_bucket(farrier_id, sku_id)
        if bucket is None or bucket["available_pairs"] < pairs:
            raise ApiError("ERR_VAN_STOCK_INSUFFICIENT")
    return required


def apply_reservations_for_attach(appointment, farrier_id, required):
    """Create a RESERVED row per distinct SKU, or re-reserve a RELEASED one."""
    existing = {r["sku_id"]: r for r in reservations_of(appointment)}
    for sku_id, pairs in required.items():
        bucket = van_bucket(farrier_id, sku_id)
        reservation = existing.get(sku_id)
        if reservation is None:
            db.mint(
                "shoe_reservations",
                {
                    "appointment_id": appointment["id"],
                    "sku_id": sku_id,
                    "bucket_id": bucket["id"],
                    "pairs": pairs,
                    "status": "RESERVED",
                },
            )
        else:
            reservation["bucket_id"] = bucket["id"]
            reservation["pairs"] = pairs
            reservation["status"] = "RESERVED"
            db.touch(reservation)
        move_bucket(bucket, available=-pairs, reserved=pairs)


def resync_reservations(appointment, farrier_id, dry_run=False):
    """Recompute an attached visit's reservations after a service-line change.

    Surplus pairs return to the van bucket's ``available_pairs``; a shortfall is
    taken from it.  With ``dry_run`` the availability is only checked.
    """
    required = shoe_pairs_required(appointment)
    current = {}
    for reservation in reservations_of(appointment, ("RESERVED",)):
        current[reservation["sku_id"]] = reservation

    for sku_id, pairs in required.items():
        held = current[sku_id]["pairs"] if sku_id in current else 0
        delta = pairs - held
        if delta <= 0:
            continue
        bucket = van_bucket(farrier_id, sku_id)
        if bucket is None or bucket["available_pairs"] < delta:
            raise ApiError("ERR_VAN_STOCK_INSUFFICIENT")
    if dry_run:
        return

    existing_any = {r["sku_id"]: r for r in reservations_of(appointment)}
    for sku_id, reservation in current.items():
        if sku_id in required:
            continue
        bucket = db.get("inventory_buckets", reservation["bucket_id"])
        reservation["status"] = "RELEASED"
        db.touch(reservation)
        if bucket is not None:
            move_bucket(bucket, available=reservation["pairs"], reserved=-reservation["pairs"])

    for sku_id, pairs in required.items():
        bucket = van_bucket(farrier_id, sku_id)
        reservation = existing_any.get(sku_id)
        if reservation is None:
            db.mint(
                "shoe_reservations",
                {
                    "appointment_id": appointment["id"],
                    "sku_id": sku_id,
                    "bucket_id": bucket["id"],
                    "pairs": pairs,
                    "status": "RESERVED",
                },
            )
            move_bucket(bucket, available=-pairs, reserved=pairs)
        elif reservation["status"] == "RESERVED":
            delta = pairs - reservation["pairs"]
            if delta:
                reservation["pairs"] = pairs
                db.touch(reservation)
                move_bucket(bucket, available=-delta, reserved=delta)
        else:
            reservation["bucket_id"] = bucket["id"]
            reservation["pairs"] = pairs
            reservation["status"] = "RESERVED"
            db.touch(reservation)
            move_bucket(bucket, available=-pairs, reserved=pairs)
