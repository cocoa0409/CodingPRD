"""Business services: state-machine side effects, cascades, reconciliation."""
from decimal import Decimal

import calc
import db
from db import bump
from serialize import order_total_paid, order_allocated_sqft
from util import D


# --------------------------------------------------------------------- fields
def maturity_scan(field):
    """Persist the recomputed maturity_state; fire the conditional OVERAGED
    cascade only when the persisted value actually changes INTO OVERAGED.
    Recomputation never increments Field.version and never touches updated_at."""
    _, state = calc.compute_maturity(field)
    old = field["maturity_state"]
    if state == old:
        return
    field["maturity_state"] = state
    if state == "OVERAGED":
        _cascade_overaged(field)


def _cascade_overaged(field):
    """3-hop cascade: field -> PENDING batches CANCELLED -> under-allocated
    CONFIRMED orders revert to PLACED with ALL batch links removed."""
    just_cancelled = set()
    for b in db.store.harvest_batches.values():
        if b["field_id"] == field["id"] and b["status"] == "PENDING":
            b["status"] = "CANCELLED"
            bump(b)
            just_cancelled.add(b["id"])
    for o in db.store.orders.values():
        if o["status"] != "CONFIRMED":
            continue
        if order_allocated_sqft(o) >= D(o["turf_sqft"]):
            continue
        # revert: window cleared (capacity released), all batch links removed
        o["status"] = "PLACED"
        o["delivery_window_start"] = None
        o["delivery_window_end"] = None
        for b in db.store.harvest_batches.values():
            if b["order_id"] == o["id"]:
                b["order_id"] = None
                if b["id"] not in just_cancelled:
                    # batches cancelled above were already bumped by this cascade
                    bump(b)
        bump(o)


def reseed_complete_cascade(field):
    """Crop-cycle reset: SEEDED, replanted now, full area restored, mow log
    zeroed; stubble (PENDING batches + unlinked COMPLETE batches) cancelled."""
    field["maturity_state"] = "SEEDED"
    field["last_planted_at"] = db.now()
    field["remaining_sqft"] = D(field["field_sqft"])
    field["mow_count"] = 0
    bump(field)
    for b in db.store.harvest_batches.values():
        if b["field_id"] != field["id"]:
            continue
        if b["status"] == "PENDING" or (b["status"] == "COMPLETE" and b["order_id"] is None):
            b["status"] = "CANCELLED"
            bump(b)


# --------------------------------------------------------------------- crews
def crew_deactivate_cascade(crew):
    """2-hop cascade: live referrals of this crew -> REPLACED; affected orders
    crew_referral_status -> NONE."""
    for r in db.store.crew_referrals.values():
        if r["crew_id"] == crew["id"] and r["status"] in ("REFERRED", "SCHEDULED"):
            r["status"] = "REPLACED"
            bump(r)
            order = db.store.orders.get(r["order_id"])
            if order is not None and order["crew_referral_status"] != "NONE":
                order["crew_referral_status"] = "NONE"
                bump(order)


# --------------------------------------------------------------------- orders
def reconcile_order(order):
    """Fiscal reconciliation after every payment / delivery check.

    payment_status = PAID iff amount_due == 0; auto-join to CLOSED when a
    payment-side flip leaves an INSTALLED order fully settled."""
    total_paid = order_total_paid(order)
    chargeable = D(order["chargeable_amount"])
    amount_due = chargeable - total_paid
    order["payment_status"] = "PAID" if amount_due <= 0 else "PENDING"
    if order["payment_status"] == "PAID" and order["status"] == "INSTALLED":
        order["status"] = "CLOSED"


def release_allocation(order):
    """Detach every non-cancelled linked batch (order cancel)."""
    for b in db.store.harvest_batches.values():
        if b["order_id"] == order["id"] and b["status"] != "CANCELLED":
            b["order_id"] = None
            bump(b)


def cancel_order_cascade(order):
    release_allocation(order)
    for r in db.store.crew_referrals.values():
        if r["order_id"] == order["id"] and r["status"] in ("REFERRED", "SCHEDULED"):
            r["status"] = "REPLACED"
            bump(r)
    order["crew_referral_status"] = "NONE"


# ------------------------------------------------------------------ referrals
def live_referral(order_id):
    """The order's unique non-terminal referral, if any."""
    for r in db.store.crew_referrals.values():
        if r["order_id"] == order_id and r["status"] in ("REFERRED", "SCHEDULED"):
            return r
    return None
