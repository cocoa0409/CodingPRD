"""State-machine guards, cascades and shared workflow effects."""
from decimal import Decimal

import calc
from calc import (ORDER_OPEN_STATES, governing_permit, permit_satisfactory,
                  recompute_asset, recompute_exposure, recompute_farm,
                  recompute_tank, tank_orders, order_uplifts, order_account_id)
from core import ApiError, D, db, now, now_iso, parse_dt, touch

TERMINAL = {
    "receipt": ("RELEASED", "REJECTED"),
    "order": ("COMPLETED", "CANCELLED", "ABORTED"),
    "authorization": ("REDEEMED", "VOIDED", "EXPIRED"),
    "spill": ("CLOSED",),
    "invoice": ("PAID", "VOIDED"),
    "run": ("POSTED",),
}


def terminal_guard(kind, status):
    if status in TERMINAL[kind]:
        raise ApiError("ERR_ALREADY_TERMINAL", "Row is already in terminal state %s" % status)


def farm_of_tank(tank):
    return db.farms.get(tank["fuel_farm_id"])


def farm_of_asset(asset):
    return db.farms.get(asset["fuel_farm_id"])


def order_tank(order):
    return db.tanks.get(order["storage_tank_id"])


def order_farm(order):
    tank = order_tank(order)
    return farm_of_tank(tank) if tank else None


def refresh_farm(farm):
    """Read-time / write-time posture refresh (no version bump of its own)."""
    if farm is None:
        return None
    recompute_farm(farm)
    return farm


def frozen_guard(farm):
    refresh_farm(farm)
    if farm["posture"] == "FROZEN":
        raise ApiError("ERR_FARM_FROZEN", "Farm posture is FROZEN")


def permit_guard(farm):
    permit = governing_permit(farm["id"])
    if not permit_satisfactory(permit):
        raise ApiError("ERR_PERMIT_NOT_ACTIVE",
                       "Farm has no ACTIVE permit covering the current logical clock")
    return permit


def posture_and_permit_guard(farm):
    """Combined guard for the four operations that carry both the frozen-farm guard and the
    active-permit guard (receipt creation, receipt verdict, order authorization and uplift
    posting).

    PRD: "Operations that a `FROZEN` posture blocks are rejected with `ERR_FARM_FROZEN`, and
    when the block is specifically the absence of a satisfactory permit the rejection is
    `ERR_PERMIT_NOT_ACTIVE`." So on these four the freeze cause has to be inspected: a freeze
    whose cause is an unsatisfactory governing permit reports the permit error, while a freeze
    from any other cause (an escalated spill) still reports the freeze. Operations that carry
    only the frozen-farm guard keep reporting `ERR_FARM_FROZEN` whatever the cause.
    """
    refresh_farm(farm)
    permit = permit_guard(farm)
    if farm["posture"] == "FROZEN":
        raise ApiError("ERR_FARM_FROZEN", "Farm posture is FROZEN")
    return permit


def expire_authorization(auth):
    """Lazy ISSUED -> EXPIRED evaluation against the logical clock."""
    if auth is None:
        return None
    if auth["status"] == "ISSUED" and now() >= parse_dt(auth["expires_at_utc"]):
        auth["status"] = "EXPIRED"
        touch(auth)
    return auth


def void_authorization(auth, reason):
    if auth is None:
        return
    expire_authorization(auth)
    if auth["status"] == "ISSUED":
        auth["status"] = "VOIDED"
        auth["voided_reason"] = reason
        touch(auth)


def recompute_order_posted(order):
    total = D(0)
    for u in order_uplifts(order["id"]):
        if u["status"] in ("POSTED", "BILLED"):
            total += D(u["net_liters"])
    order["posted_net_liters"] = float(calc.q2(total))
    return order


# ------------------------------------------------------------- pit occupancy
def end_pit_occupancy(order):
    """The order's pit occupancy ends when it leaves the ASSIGNED/FUELING set."""
    pit_id = order.get("hydrant_pit_id")
    order["hydrant_pit_id"] = None
    pit = db.pits.get(pit_id) if pit_id else None
    if pit is not None:
        touch(pit)
    return pit


def pit_occupied_windows(pit_id, exclude_order_id=None):
    out = []
    for o in db.orders.values():
        if o.get("hydrant_pit_id") != pit_id:
            continue
        if o["status"] not in ("ASSIGNED", "FUELING"):
            continue
        if exclude_order_id and o["id"] == exclude_order_id:
            continue
        out.append(o)
    return out


# ------------------------------------------------------------- order closures
def void_order_uplifts(order, tank):
    for u in order_uplifts(order["id"]):
        if u["status"] != "POSTED":
            continue
        u["status"] = "VOIDED"
        u["voided_reason"] = "ORDER_ABORTED"
        touch(u)
        asset = db.assets.get(order.get("fueling_asset_id"))
        if asset is not None and u.get("_filter_epoch") == asset.get("_filter_epoch"):
            asset["liters_since_filter_change"] = float(
                calc.q2(D(asset["liters_since_filter_change"]) - D(u["net_liters"])))


def abort_order(order, reason, auth_reason="ORDER_CANCELLED"):
    """FUELING -> ABORTED with the full compensation set."""
    tank = order_tank(order)
    asset = db.assets.get(order.get("fueling_asset_id"))
    auth = db.authorizations.get(order.get("fuel_authorization_id"))
    account = db.accounts.get(order_account_id(order))

    void_order_uplifts(order, tank)
    order["status"] = "ABORTED"
    order["abort_reason"] = reason
    end_pit_occupancy(order)
    recompute_order_posted(order)
    touch(order)

    if tank is not None:
        recompute_tank(tank)
        touch(tank)
    if asset is not None:
        recompute_asset(asset)
        touch(asset)
    void_authorization(auth, auth_reason)
    if account is not None:
        recompute_exposure(account)
        touch(account)
    farm = farm_of_tank(tank) if tank else None
    refresh_farm(farm)


def unassign_order(order):
    """ASSIGNED -> AUTHORIZED. Reservation untouched."""
    asset = db.assets.get(order.get("fueling_asset_id"))
    order["status"] = "AUTHORIZED"
    order["fueling_asset_id"] = None
    end_pit_occupancy(order)
    order["unassign_count"] = order["unassign_count"] + 1
    touch(order)
    if asset is not None:
        touch(asset)


def cancel_order(order, auth_reason="ORDER_CANCELLED"):
    """Cancels the order from REQUESTED, AUTHORIZED or ASSIGNED."""
    prev = order["status"]
    tank = order_tank(order)
    auth = db.authorizations.get(order.get("fuel_authorization_id"))
    account = db.accounts.get(order_account_id(order))

    if prev == "ASSIGNED":
        end_pit_occupancy(order)
        order["fueling_asset_id"] = None
    order["status"] = "CANCELLED"
    touch(order)
    if prev in ("AUTHORIZED", "ASSIGNED") and tank is not None:
        recompute_tank(tank)
        touch(tank)
    void_authorization(auth, auth_reason)
    if prev in ("AUTHORIZED", "ASSIGNED") and account is not None:
        recompute_exposure(account)
        touch(account)
    refresh_farm(farm_of_tank(tank) if tank else None)


# ------------------------------------------------------------- cascades
def quarantine_tank_cascade(tank):
    """Cascade hops 2 and 3 following a tank quality quarantine."""
    for order in sorted(tank_orders(tank["id"]), key=lambda o: (o["created_at"], o["_seq"])):
        if order["status"] == "ASSIGNED":
            unassign_order(order)
        elif order["status"] == "FUELING":
            abort_order(order, "QUALITY_HOLD", "ORDER_CANCELLED")
    recompute_tank(tank)
    refresh_farm(farm_of_tank(tank))


def quarantine_tank(tank):
    """Hop 1 plus hops 2 and 3; assumes the state guard has already been applied."""
    tank["quality_status"] = "QUARANTINED"
    quarantine_tank_cascade(tank)


def freeze_cascade(farm, abort_reason="SPILL"):
    """Hops 2 and 3 of the farm FROZEN cascade."""
    orders = [o for o in db.orders.values()
              if (db.tanks.get(o["storage_tank_id"]) or {}).get("fuel_farm_id") == farm["id"]]
    orders.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for order in orders:
        if order["status"] == "AUTHORIZED":
            cancel_order(order, "FARM_FROZEN")
        elif order["status"] == "FUELING":
            abort_order(order, abort_reason, "FARM_FROZEN")
    for asset in sorted(calc.farm_assets(farm["id"]), key=lambda a: (a["created_at"], a["_seq"])):
        if asset["status"] in ("IN_SERVICE", "FILTER_DUE"):
            asset["status"] = "DOWN_MAINTENANCE"
            calc.recompute_asset(asset, auto_status=False)
            touch(asset)
    refresh_farm(farm)


def apply_posture_change(farm, abort_reason="SPILL"):
    """Recompute posture; if the farm has become FROZEN, run the freeze cascade."""
    refresh_farm(farm)
    if farm["posture"] == "FROZEN":
        freeze_cascade(farm, abort_reason)
    return farm


# ------------------------------------------------------------- receipts / samples
def latest_tested_sample(receipt_id):
    samples = [s for s in db.samples.values()
               if s.get("fuel_receipt_id") == receipt_id and s["status"] == "TESTED"]
    if not samples:
        return None
    samples.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return samples[-1]


def latest_tank_sample(tank_id):
    samples = [s for s in db.samples.values() if s.get("storage_tank_id") == tank_id]
    if not samples:
        return None
    samples.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return samples[-1]


def latest_periodic_pass(tank_id):
    """The latest sample for the tank, required to be a PASSing tested periodic QA sample."""
    latest = latest_tank_sample(tank_id)
    if latest is None:
        return None
    if latest["sample_purpose"] != "PERIODIC_TANK_QA":
        return None
    if latest["status"] != "TESTED" or latest.get("verdict") != "PASS":
        return None
    return latest


def maybe_heal_tank(tank):
    """After a receipt rejection: return the tank to RELEASED when nothing holds it."""
    if tank["quality_status"] != "QUARANTINED":
        return
    for r in calc.tank_receipts(tank["id"]):
        if r["status"] == "QUARANTINED":
            return
    if latest_periodic_pass(tank["id"]) is not None:
        tank["quality_status"] = "RELEASED"
