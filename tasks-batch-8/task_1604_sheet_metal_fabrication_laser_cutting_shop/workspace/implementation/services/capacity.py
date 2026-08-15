"""Machine capacity accounting over the rolling 12-day horizon at the 0.90 cap."""
from datetime import timedelta

import db
from db import store

HORIZON_DAYS = 12


def booked_minutes(machine_id, exclude_order_id=None):
    """Sum of planned_minutes of PENDING/IN_PROGRESS steps on the machine whose
    due_date falls within [now, now + 12d]. Cancelled orders hold no load."""
    now = db.LOGICAL_CLOCK
    horizon_end = now + timedelta(days=HORIZON_DAYS)
    total = 0
    for st in store.routing_steps.values():
        if st.get("machine_id") != machine_id:
            continue
        if st["status"] not in ("PENDING", "IN_PROGRESS"):
            continue
        if exclude_order_id and st["order_id"] == exclude_order_id:
            continue
        order = store.orders.get(st["order_id"])
        if order is not None and order["status"] == "CANCELLED":
            continue
        due = st.get("_due_dt")
        if due is not None and now <= due <= horizon_end:
            total += st["planned_minutes"]
    return total


def can_absorb(machine, booked, planned):
    """booked + planned <= 0.90 * capacity, inclusive at the cap (exact integer math)."""
    capacity = machine["shift_minutes_per_day"] * HORIZON_DAYS
    return 10 * (booked + planned) <= 9 * capacity


def select_machine(station, planned_minutes, exclude_order_id=None):
    """Least-booked feasible ACTIVE machine of the station; tie-break earliest created."""
    candidates = [m for m in store.machines.values()
                  if m["station"] == station and m["status"] == "ACTIVE"]
    candidates.sort(key=lambda m: (booked_minutes(m["id"], exclude_order_id),
                                   m["created_at"], m["_seq"]))
    for m in candidates:
        if can_absorb(m, booked_minutes(m["id"], exclude_order_id), planned_minutes):
            return m
    return None
