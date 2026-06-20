"""Existence resolution and ownership chains (PRD §2.5, §2.1)."""
from db import db
from errors import err


def get_owner(owner_id):
    o = db.owners.get(owner_id)
    if o is None:
        raise err("ERR_OWNER_NOT_FOUND", "Owner not found")
    return o


def get_waiver(waiver_id):
    w = db.waivers.get(waiver_id)
    if w is None:
        raise err("ERR_WAIVER_NOT_FOUND", "Waiver not found")
    return w


def get_stall(stall_id):
    s = db.stalls.get(stall_id)
    if s is None:
        raise err("ERR_STALL_NOT_FOUND", "Stall not found")
    return s


def get_horse(horse_id):
    h = db.horses.get(horse_id)
    if h is None:
        raise err("ERR_HORSE_NOT_FOUND", "Horse not found")
    return h


def get_agreement(agreement_id):
    a = db.agreements.get(agreement_id)
    if a is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", "Boarding agreement not found")
    return a


def get_lesson(lesson_id):
    l = db.lessons.get(lesson_id)
    if l is None:
        raise err("ERR_LESSON_NOT_FOUND", "Lesson not found")
    return l


def get_visit(visit_id):
    v = db.visits.get(visit_id)
    if v is None:
        raise err("ERR_VISIT_NOT_FOUND", "Service visit not found")
    return v


def get_entry(entry_id):
    e = db.entries.get(entry_id)
    if e is None:
        raise err("ERR_ENTRY_NOT_FOUND", "Show entry not found")
    return e


def get_turnout(turnout_id):
    t = db.turnouts.get(turnout_id)
    if t is None:
        raise err("ERR_TURNOUT_NOT_FOUND", "Turnout assignment not found")
    return t


def get_invoice(invoice_id):
    i = db.invoices.get(invoice_id)
    if i is None:
        raise err("ERR_INVOICE_NOT_FOUND", "Invoice not found")
    return i


# ----- ownership resolution (PRD §2.1) -----

def owner_id_of_horse(horse):
    return horse["owner_id"]


def owner_id_via_horse(horse_id):
    horse = db.horses.get(horse_id)
    if horse is None:
        return None
    return horse["owner_id"]


def require_owner_owns(caller, resource_owner_id):
    """For Owner-scoped writes: X-User-ID must equal the resolved owner id.
    ERR_NOT_RESOURCE_OWNER (403) otherwise (PRD §2.1)."""
    if caller.role == "Owner" and caller.user_id != resource_owner_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting owner does not own this resource")


def owner_has_active_waiver(owner_id):
    """True if the owner holds a SIGNED non-expired waiver at the current clock.
    Lazy expiry is realized only on waiver-list reads (PRD §3.4); this is a pure
    point-in-time check used by activation/completion/confirmation guards, so we
    also treat a SIGNED waiver whose expires_at the clock has reached/passed as
    not active (inclusive boundary)."""
    now = db.clock.now
    from clock import parse_iso
    for w in db.waivers.values():
        if w["owner_id"] != owner_id:
            continue
        if w["status"] != "SIGNED":
            continue
        # inclusive expiry boundary: at exactly expires_at the waiver is expired
        exp = parse_iso(w["expires_at"]) if w["expires_at"] else None
        if exp is not None and now >= exp:
            continue
        return True
    return False
