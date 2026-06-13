"""Entity lookup, mutation bookkeeping, and serialization helpers."""
import errors
from errors import err
from db import db, now_iso


def touch(entity):
    """Refresh updated_at and bump version by 1 (PRD §2.4 / §2.6)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


# ---- lookups (raise ERR_NOT_FOUND when absent) ----

def get_venue(vid):
    v = db.venues.get(vid)
    if v is None:
        raise err(errors.ERR_NOT_FOUND, "Venue not found")
    return v


def get_room(rid):
    r = db.rooms.get(rid)
    if r is None:
        raise err(errors.ERR_NOT_FOUND, "Room not found")
    return r


def get_pricing_rule(pid):
    p = db.pricing_rules.get(pid)
    if p is None:
        raise err(errors.ERR_NOT_FOUND, "Pricing rule not found")
    return p


def get_game_master(gid):
    g = db.game_masters.get(gid)
    if g is None:
        raise err(errors.ERR_NOT_FOUND, "Game master not found")
    return g


def get_slot(sid):
    s = db.time_slots.get(sid)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Time slot not found")
    return s


def get_customer(cid):
    c = db.customers.get(cid)
    if c is None:
        raise err(errors.ERR_NOT_FOUND, "Customer not found")
    return c


def get_booking(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise err(errors.ERR_NOT_FOUND, "Booking not found")
    return b


def get_participant(pid):
    p = db.participants.get(pid)
    if p is None:
        raise err(errors.ERR_NOT_FOUND, "Participant not found")
    return p


def get_gift_card(gid):
    g = db.gift_cards.get(gid)
    if g is None:
        raise err(errors.ERR_NOT_FOUND, "Gift card not found")
    return g


def get_gift_card_entry(eid):
    e = db.gift_card_entries.get(eid)
    if e is None:
        raise err(errors.ERR_NOT_FOUND, "Gift card entry not found")
    return e


# ---- computed-field projection on read ----

def gm_active_count(gm_id):
    return sum(
        1 for s in db.time_slots.values()
        if s.get("assigned_game_master_id") == gm_id
        and s["status"] in ("HELD", "BOOKED")
    )


def customer_strikes(customer_id):
    return sum(
        1 for b in db.bookings.values()
        if b.get("customer_id") == customer_id
        and b["lifecycle_status"] == "NO_SHOW"
    )


def gift_card_balance(gift_card_id, gc=None):
    if gc is None:
        gc = db.gift_cards.get(gift_card_id)
    total = gc["initial_balance_cents"]
    for e in db.gift_card_entries.values():
        if e["gift_card_id"] == gift_card_id:
            total += e["delta_cents"]
    return total


# ---- serialization (strip nothing; computed fields kept consistent) ----

def ser_venue(v):
    return dict(v)


def ser_room(r):
    return dict(r)


def ser_pricing_rule(p):
    return dict(p)


def ser_game_master(g):
    out = dict(g)
    out["active_assignment_count"] = gm_active_count(g["id"])
    return out


def ser_slot(s):
    return dict(s)


def ser_customer(c):
    out = dict(c)
    out["no_show_strike_count"] = customer_strikes(c["id"])
    return out


def ser_booking(b):
    return dict(b)


def ser_participant(p):
    return dict(p)


def ser_gift_card(g):
    out = dict(g)
    out["balance_cents"] = gift_card_balance(g["id"], g)
    return out


def ser_gift_card_entry(e):
    return dict(e)
