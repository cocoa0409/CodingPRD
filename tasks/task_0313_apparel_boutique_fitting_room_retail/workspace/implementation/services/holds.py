"""Fitting-room hold sweep logic, invoked by the store-clock advance (PRD §3.3)."""
from db import db, touch
from services.common import recompute_variant


def sweep_expired_holds(boutique_id, new_business_date, new_minute):
    """Expire ACTIVE/EXTENDED holds whose interval has passed.

    A hold expires when its business day has been left behind by an advancing
    current_business_date, OR (still on its own day) its end_minute is at or
    before the current minute. Expiry frees the reservation exactly like a
    release: decrement reserved by 1, recompute available, bubble up.
    """
    # Holds are linked to fitting rooms, which belong to a boutique.
    room_ids = {
        r["id"] for r in db.fitting_rooms.values() if r["boutique_id"] == boutique_id
    }
    for hold in db.fitting_room_holds.values():
        if hold["fitting_room_id"] not in room_ids:
            continue
        if hold["status"] not in ("ACTIVE", "EXTENDED"):
            continue
        hold_day = hold["_business_date"]
        expired = False
        if new_business_date > hold_day:
            # Business day advanced past the hold's day.
            expired = True
        elif new_business_date == hold_day and new_minute is not None and hold["end_minute"] <= new_minute:
            expired = True
        if expired:
            hold["status"] = "EXPIRED"
            touch(hold)
            variant = db.sku_variants.get(hold["sku_variant_id"])
            if variant is not None:
                variant["reserved"] = max(0, variant["reserved"] - 1)
                recompute_variant(variant)
