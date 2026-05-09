"""POST /_clock/advance — runs every auto-transition due at or before the new instant.

Four classes (PRD §3.10):
  1. FeeBill OPEN -> OVERDUE + dunning escalation
  2. WorkOrder RESOLVED -> CONFIRMED (auto, satisfaction_score=5) when now>=confirm_deadline_at
  3. Reservation BOOKED -> NO_SHOW + forfeit deposit when now>=slot_end_at

Transitions are applied in chronological order — we first sort the candidate
events by their trigger instant before applying.
"""
from __future__ import annotations

from datetime import datetime

import db
from services.common import bump
from services.fees import auto_transition_overdue_and_dunning
from utils import parse_iso


def _auto_confirm_work_orders(now: datetime) -> None:
    """Walk RESOLVED orders whose confirm_deadline_at has passed."""
    candidates = []
    for wo in db.work_orders.values():
        if wo.get("status") != "RESOLVED":
            continue
        deadline_str = wo.get("confirm_deadline_at")
        if not deadline_str:
            continue
        deadline = parse_iso(deadline_str, field="confirm_deadline_at")
        if now >= deadline:
            candidates.append((deadline, wo))
    candidates.sort(key=lambda pair: pair[0])
    for _deadline, wo in candidates:
        wo["satisfaction_score"] = 5
        wo["status"] = "CONFIRMED"
        bump(wo)


def _auto_no_show_reservations(now: datetime) -> None:
    """Walk BOOKED reservations whose slot_end_at has passed."""
    candidates = []
    for r in db.reservations.values():
        if r.get("status") != "BOOKED":
            continue
        end = parse_iso(r["slot_end_at"], field="slot_end_at")
        if now >= end:
            candidates.append((end, r))
    candidates.sort(key=lambda pair: pair[0])
    for _end, r in candidates:
        # Forfeit the entire held deposit
        r["deposit_held"] = 0.0
        r["status"] = "NO_SHOW"
        bump(r)


def advance_to(target: datetime) -> None:
    """Set the logical clock and run all auto-transitions due at or before."""
    db.set_clock(target)
    auto_transition_overdue_and_dunning()
    _auto_confirm_work_orders(target)
    _auto_no_show_reservations(target)
