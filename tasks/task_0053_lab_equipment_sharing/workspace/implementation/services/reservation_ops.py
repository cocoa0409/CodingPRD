"""Reservation cancellation cascade logic — used by maintenance, authorization,
preemption, and user cancel paths.
"""
from decimal import Decimal

import db
from clock import iso, now
from services import audit, calc


def cancel_reservation(reservation: dict, actor_role: str, actor_user_id: str,
                       refund_bps: int, reason: str = "system_cascade") -> None:
    """Mutates `reservation` in place: status -> CANCELLED with the supplied
    refund_bps. Debits Lab.settlement_balance_cents and emits audit row.

    Does NOT validate state — caller is responsible for ensuring transition is legal.
    """
    if reservation["status"] not in ("BOOKED",):
        # Defensive: only cancel from BOOKED
        return
    prev = reservation["status"]
    reservation["status"] = "CANCELLED"
    reservation["cancelled_at"] = iso(now())
    reservation["cancellation_refund_bps"] = refund_bps
    db.stamp_update(reservation)

    # Debit the lab settlement balance by estimated_owner_share * refund_bps / 10000
    lab = db.labs.get(_lab_id_for_reservation(reservation))
    if lab is not None:
        accrued = int(reservation.get("estimated_owner_share_cents", 0) or 0)
        if accrued > 0 and refund_bps > 0:
            debit = calc.round_half_up(Decimal(accrued) * Decimal(refund_bps) / Decimal(10000))
            lab["settlement_balance_cents"] = int(lab["settlement_balance_cents"]) - debit
            db.stamp_update(lab)

    audit.record(
        subject_type="RESERVATION",
        subject_id=reservation["id"],
        actor_role=actor_role,
        actor_user_id=actor_user_id,
        action="CANCEL",
        from_state=prev,
        to_state="CANCELLED",
        payload_json={
            "reason": reason,
            "cancellation_refund_bps": refund_bps,
        },
    )


def _lab_id_for_reservation(reservation: dict):
    eq = db.equipment.get(reservation["equipment_id"])
    if eq is None:
        return None
    return eq["lab_id"]


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    """Half-open intersection check."""
    return a_start < b_end and b_start < a_end


def find_overlapping_reservations(equipment_id: str, start_at, end_at,
                                  statuses=("BOOKED",)):
    """Return list of reservations on the equipment whose [start_at,end_at) intersects."""
    out = []
    for r in db.reservations.values():
        if r["equipment_id"] != equipment_id:
            continue
        if r["status"] not in statuses:
            continue
        from clock import parse_iso
        rs = parse_iso(r["start_at"])
        re_ = parse_iso(r["end_at"])
        if overlaps(start_at, end_at, rs, re_):
            out.append(r)
    return out
