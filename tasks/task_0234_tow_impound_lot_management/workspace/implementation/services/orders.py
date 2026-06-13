"""TowOrder accrual ledger management + computed-field recompute."""
import db
from clock import iso, now, parse_iso
from services import calc


def order_ledger_segments(order_id):
    """All ledger entries for an order, ordered by creation sequence."""
    segs = [e for e in db.ledger_entries.values() if e["tow_order_id"] == order_id]
    segs.sort(key=lambda e: e["_seq"])
    return segs


def open_segment(order_id):
    """The currently-open accrual/resume segment (segment_end None), if any.
    Tracked by its accrual origin (_accrual_kind in {ACCRUAL, RESUME}), which is
    independent of the displayed `kind` (which becomes FREEZE once closed)."""
    for seg in order_ledger_segments(order_id):
        if seg.get("_accrual_kind") in ("ACCRUAL", "RESUME") and seg.get("_segment_end_dt") is None:
            return seg
    return None


def open_accrual(order, lot, kind, start_dt):
    """Open a fresh ACCRUAL/RESUME segment with a not-yet-set end.
    `_accrual_kind` records the accrual origin; the public `kind` starts equal to
    it and is relabeled FREEZE when the segment is closed by a freeze."""
    entry = {
        "tow_order_id": order["id"],
        "segment_start": iso(start_dt),
        "segment_end": None,
        "days_counted": None,
        "segment_charge_cents": None,
        "kind": kind,
        "_accrual_kind": kind,
        "_segment_start_dt": start_dt,
        "_segment_end_dt": None,
    }
    entry["id"] = db.new_id()
    entry["created_at"] = iso(now())
    entry["_seq"] = db.next_seq()
    db.ledger_entries[entry["id"]] = entry
    return entry


def close_open_segment(order, lot, end_dt, kind):
    """Close the currently-open segment: set its end, finalize days_counted /
    segment_charge_cents, and relabel its displayed `kind` (e.g. FREEZE). The
    segment's accrual contribution (_accrual_kind + stored charge) is preserved."""
    seg = open_segment(order["id"])
    if seg is None:
        return None
    seg["_segment_end_dt"] = end_dt
    seg["segment_end"] = iso(end_dt)
    days = calc.days_between(seg["_segment_start_dt"], end_dt)
    seg["days_counted"] = days
    seg["segment_charge_cents"] = days * lot["daily_storage_rate_cents"]
    seg["kind"] = kind
    return seg


def lot_of(order):
    return db.impound_lots.get(order["lot_id"])


def recompute(order):
    """Recompute all computed fields on a tow order in place (does NOT bump version)."""
    lot = lot_of(order)
    if lot is None:
        return order
    segs = order_ledger_segments(order["id"])
    acc_days, acc_cents = calc.accrued(order, lot, segs)
    order["accrued_days"] = acc_days
    order["accrued_storage_cents"] = acc_cents
    order["balance_due_cents"] = calc.balance_due(order, lot)
    order["net_due_cents"] = calc.net_due(order["balance_due_cents"], order.get("waiver_credit_cents", 0))
    return order


def freeze_accrual(order, lot, freeze_dt):
    """Close the open segment as a FREEZE, set accrual_frozen_at, recompute."""
    close_open_segment(order, lot, freeze_dt, "FREEZE")
    order["accrual_frozen_at"] = iso(freeze_dt)
    order["_accrual_frozen_dt"] = freeze_dt
    recompute(order)


def resume_accrual(order, lot, resume_dt):
    """Open a new RESUME segment, clear accrual_frozen_at, recompute."""
    order["accrual_frozen_at"] = None
    order["_accrual_frozen_dt"] = None
    open_accrual(order, lot, "RESUME", resume_dt)
    recompute(order)


def zero_accrual(order, lot, end_dt):
    """VOID: close any open segment and zero all fee accrual."""
    close_open_segment(order, lot, end_dt, "FREEZE")
    order["accrued_days"] = 0
    order["accrued_storage_cents"] = 0
    order["balance_due_cents"] = 0
    order["waiver_credit_cents"] = 0
    order["net_due_cents"] = 0
    order["accrual_frozen_at"] = iso(end_dt)
    order["_accrual_frozen_dt"] = end_dt


def statutory_eligible(order):
    """Boolean gate (scaffold statutory_eligibility): both the hold period and a
    qualifying notice grace window must have elapsed."""
    lot = lot_of(order)
    if lot is None:
        return False
    cur = now()
    intake = order.get("_intake_dt")
    hold_days = calc.days_between(intake, cur)
    if hold_days < lot["statutory_hold_days"]:
        return False
    # A qualifying notification: DELIVERY_CONFIRMED or CERTIFIED_RETURNED whose
    # grace window has elapsed.
    for notif in db.notifications.values():
        if notif["tow_order_id"] != order["id"]:
            continue
        if notif["status"] not in ("DELIVERY_CONFIRMED", "CERTIFIED_RETURNED"):
            continue
        resolved = notif.get("_resolved_dt")
        if resolved is None:
            continue
        grace_days = calc.days_between(resolved, cur)
        if grace_days >= lot["notice_grace_days"]:
            return True
    return False
