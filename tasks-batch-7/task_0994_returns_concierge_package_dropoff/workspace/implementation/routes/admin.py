"""Test-driving endpoints: logical clock control and the expiry sweep."""

import db
from db import store, touch, fmt_s
from util import require_roles, respond, body, req_dt
from flask import Blueprint

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    b = body(required=True)
    db.set_now(req_dt(b, "to_iso8601"))
    return respond({"current_utc": fmt_s(db.now())})


@bp.post("/_maintenance/run_sweep")
def run_sweep():
    """label_expiry calculation: candidates in created_at ASC order.
    Step 1 expires labels (dragging bound HELD reservations down);
    step 2 expires reservations whose 48h hold elapsed (freeing slots)."""
    require_roles("PlatformAdmin")
    now = db.now()
    expired_labels = 0
    expired_reservations = 0

    labels = sorted(
        (l for l in store["labels"].values()
         if l["status"] == "ISSUED" and l["expires_at"] <= now),
        key=lambda l: (l["created_at"], l["_seq"]),
    )
    for label in labels:
        label["status"] = "EXPIRED"
        touch(label)
        expired_labels += 1
        # Cascade link 2: bound HELD reservation -> EXPIRED.
        for res in store["reservations"].values():
            if res.get("label_id") == label["id"] and res["status"] == "HELD":
                res["status"] = "EXPIRED"
                touch(res)
                expired_reservations += 1
                slot = store["slots"].get(res["slot_id"])
                if slot is not None and slot["status"] == "RESERVED":
                    slot["status"] = "EMPTY"
                    touch(slot)

    reservations = sorted(
        (r for r in store["reservations"].values()
         if r["status"] == "HELD" and r["hold_until"] <= now),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    for res in reservations:
        res["status"] = "EXPIRED"
        touch(res)
        expired_reservations += 1
        slot = store["slots"].get(res["slot_id"])
        if slot is not None and slot["status"] == "RESERVED":
            slot["status"] = "EMPTY"
            touch(slot)

    return respond({
        "expired_label_count": expired_labels,
        "expired_reservation_count": expired_reservations,
    })
