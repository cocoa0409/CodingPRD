"""Fleet credit + coupon redemption aggregations (PRD §2.11, §3.6, §3.8).

These are recomputed from the live work-order set on every read and after every
relevant mutation — derived, never patched incrementally.
"""
import db


def _vehicle_ids_of_account(fleet_account_id: str):
    return {v["id"] for v in db.vehicles.values()
            if v.get("fleet_account_id") == fleet_account_id}


def reserved_credit(fleet_account_id: str) -> int:
    """Sum of total_cents over work orders of the account's vehicles whose
    payment_status is AUTHORIZED or PAID (forward-looking)."""
    veh_ids = _vehicle_ids_of_account(fleet_account_id)
    total = 0
    for w in db.work_orders.values():
        if w["vehicle_id"] in veh_ids and w["payment_status"] in ("AUTHORIZED", "PAID"):
            total += w["total_cents"]
    return total


def settled_credit(fleet_account_id: str) -> int:
    """Sum of total_cents over work orders of the account's vehicles whose
    payment_status is PAID (money actually captured)."""
    veh_ids = _vehicle_ids_of_account(fleet_account_id)
    total = 0
    for w in db.work_orders.values():
        if w["vehicle_id"] in veh_ids and w["payment_status"] == "PAID":
            total += w["total_cents"]
    return total


def coupon_redeemed_count(code: str, shop_id: str) -> int:
    """Count of work orders whose coupon_code == code AND payment_status == PAID
    (scoped to the same shop, since codes are per-shop)."""
    n = 0
    for w in db.work_orders.values():
        if (w.get("coupon_code") == code and w["shop_id"] == shop_id
                and w["payment_status"] == "PAID"):
            n += 1
    return n
