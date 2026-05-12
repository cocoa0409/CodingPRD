"""Time-driven sweep: applied when /_clock/advance moves the logical clock forward.

Three classes of transition:
  * Reservation CONFIRMED -> NO_SHOW (when now >= check_in_date + 24h AND no check-in)
  * MaintenanceBlock SCHEDULED -> ACTIVE (when now in [start, end))
  * MaintenanceBlock ACTIVE -> RELEASED (when now >= end)
"""
from datetime import datetime, timedelta, timezone

from db import (
    reservations as reservations_table,
    maintenance_blocks,
    rooms as rooms_table,
    rate_plans,
    stamp_update,
)
from clock import parse_date, iso, now as clock_now
from services.pricing import compute_no_show_charge_cents


def _activate_block(b: dict, transitions: list):
    if b.get("status") != "SCHEDULED":
        return
    b["status"] = "ACTIVE"
    stamp_update(b)
    transitions.append({"entity": "MaintenanceBlock", "id": b["id"], "from": "SCHEDULED", "to": "ACTIVE"})

    # Cascade: room operational_status -> OUT_OF_ORDER if currently IN_SERVICE and not OCCUPIED
    rm = rooms_table.get(b["room_id"])
    if rm is None:
        return
    if rm.get("operational_status") == "IN_SERVICE" and rm.get("housekeeping_status") != "OCCUPIED":
        before = rm["operational_status"]
        rm["operational_status"] = "OUT_OF_ORDER"
        stamp_update(rm)
        transitions.append({"entity": "Room", "id": rm["id"], "from": before, "to": "OUT_OF_ORDER"})


def _release_block(b: dict, transitions: list, *, force: bool = False):
    """Release a block. force=True from explicit release call (allows ACTIVE->RELEASED at any time)."""
    if b.get("status") != "ACTIVE":
        return
    b["status"] = "RELEASED"
    stamp_update(b)
    transitions.append({"entity": "MaintenanceBlock", "id": b["id"], "from": "ACTIVE", "to": "RELEASED"})

    rm = rooms_table.get(b["room_id"])
    if rm is None:
        return
    # If no other ACTIVE block covers this room, restore operational_status -> IN_SERVICE
    has_other_active = any(
        bb.get("room_id") == rm["id"] and bb.get("status") == "ACTIVE" and bb["id"] != b["id"]
        for bb in maintenance_blocks.values()
    )
    if not has_other_active and rm.get("operational_status") == "OUT_OF_ORDER":
        before_op = rm["operational_status"]
        rm["operational_status"] = "IN_SERVICE"
        # Also flip housekeeping_status -> DIRTY (assume technician left dust)
        before_hk = rm["housekeeping_status"]
        if before_hk != "OCCUPIED":
            rm["housekeeping_status"] = "DIRTY"
        stamp_update(rm)
        transitions.append({"entity": "Room", "id": rm["id"], "from": before_op, "to": "IN_SERVICE"})


def run_time_sweep(transitions: list = None) -> list:
    """Apply all time-driven transitions based on the current clock value."""
    if transitions is None:
        transitions = []
    now_dt = clock_now()
    now_date = now_dt.date()

    # 1) Maintenance: SCHEDULED -> ACTIVE
    for b in list(maintenance_blocks.values()):
        if b.get("status") != "SCHEDULED":
            continue
        sd = parse_date(b["start_date"])
        ed = parse_date(b["end_date"])
        if now_date >= sd and now_date < ed:
            _activate_block(b, transitions)

    # 2) Maintenance: ACTIVE -> RELEASED (when now_date >= end_date)
    for b in list(maintenance_blocks.values()):
        if b.get("status") != "ACTIVE":
            continue
        ed = parse_date(b["end_date"])
        if now_date >= ed:
            _release_block(b, transitions)

    # 3) Reservation CONFIRMED -> NO_SHOW
    for r in list(reservations_table.values()):
        if r.get("booking_status") != "CONFIRMED":
            continue
        if r.get("assigned_room_id"):
            continue
        ci_date = parse_date(r["check_in_date"])
        ci_midnight = datetime.combine(ci_date, datetime.min.time(), tzinfo=timezone.utc)
        threshold = ci_midnight + timedelta(hours=24)
        if now_dt >= threshold:
            before = r["booking_status"]
            r["booking_status"] = "NO_SHOW"
            rp = rate_plans.get(r["rate_plan_id"])
            charge = compute_no_show_charge_cents(r, rp) if rp else 0
            r["no_show_charge_cents"] = charge
            r["dispute_status"] = "NONE"
            if charge > 0:
                r["payment_status"] = "CAPTURED"
            stamp_update(r)
            transitions.append({"entity": "Reservation", "id": r["id"], "from": before, "to": "NO_SHOW"})

    return transitions
