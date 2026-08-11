"""Lazy expiry sweep.

Runs on GET requests only ("the system performs this check periodically and
on any read"): expired HELD slots are RELEASED, OPEN rounds past their
deadline become EXPIRED and the surcharge is folded into the project's final
price via quote_final.

Write endpoints deliberately do NOT sweep first, so confirm-after-expiry
still yields ERR_HOLD_EXPIRED (410) and submit-after-deadline still yields
ERR_SLA_BREACH (422) instead of a swept-state 409.
"""
import db
from services.pricing import quote_final


def held_slot_expired(slot, now=None):
    if slot['status'] != 'HELD':
        return False
    exp = slot.get('held_expires_at')
    if not exp:
        return False
    now = now or db.now_dt()
    return now >= db.parse_dt(exp)


def slot_counts_as_active(slot, now=None):
    """BOOKED always counts; HELD counts only while not expired."""
    if slot['status'] == 'BOOKED':
        return True
    if slot['status'] == 'HELD':
        return not held_slot_expired(slot, now)
    return False


def sweep_expired():
    now = db.now_dt()
    for slot in list(db.session_slots.values()):
        if held_slot_expired(slot, now):
            slot['status'] = 'RELEASED'
            db.touch(slot)
    for rnd in list(db.revision_rounds.values()):
        if rnd['status'] == 'OPEN' and now > db.parse_dt(rnd['deadline_at']):
            rnd['status'] = 'EXPIRED'
            db.touch(rnd)
            proj = db.projects.get(rnd['project_id'])
            if proj is not None:
                proj['final_price_cents'] = quote_final(proj)
                db.touch(proj)
