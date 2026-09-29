"""Entity resolution (PRD 2.11 steps 4 and 5) and the space tree (PRD 2.7)."""

from db import db
from errors import err

NOT_FOUND = {
    "client": "ERR_CLIENT_NOT_FOUND",
    "space": "ERR_SPACE_NOT_FOUND",
    "policy_window": "ERR_POLICY_WINDOW_NOT_FOUND",
    "booking": "ERR_BOOKING_NOT_FOUND",
    "hold": "ERR_HOLD_NOT_FOUND",
    "license": "ERR_LICENSE_NOT_FOUND",
    "vendor": "ERR_VENDOR_NOT_FOUND",
    "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
    "service_order": "ERR_SERVICE_ORDER_NOT_FOUND",
    "labor_call": "ERR_LABOR_CALL_NOT_FOUND",
    "catering": "ERR_CATERING_NOT_FOUND",
    "settlement": "ERR_SETTLEMENT_NOT_FOUND",
    "line_item": "ERR_SETTLEMENT_NOT_FOUND",
    "blackout": "ERR_BLACKOUT_NOT_FOUND",
    "usage_record": "ERR_BOOKING_NOT_FOUND",
}


def fetch(kind, ident):
    """Resolve an id or raise the entity's own 404."""
    if not isinstance(ident, str):
        raise err(NOT_FOUND[kind])
    record = db.tables[kind].get(ident)
    if record is None:
        raise err(NOT_FOUND[kind])
    return record


def maybe(kind, ident):
    if not isinstance(ident, str):
        return None
    return db.tables[kind].get(ident)


# --------------------------------------------------------------------------
# the space tree
# --------------------------------------------------------------------------
def ancestor_ids(space_id):
    out = []
    seen = {space_id}
    current = db.spaces.get(space_id)
    while current is not None:
        parent_id = current.get("parent_space_id")
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        out.append(parent_id)
        current = db.spaces.get(parent_id)
    return out


def descendant_ids(space_id):
    out = []
    frontier = [space_id]
    seen = {space_id}
    while frontier:
        current = frontier.pop()
        for space in db.spaces.values():
            if space.get("parent_space_id") == current and space["id"] not in seen:
                seen.add(space["id"])
                out.append(space["id"])
                frontier.append(space["id"])
    return out


def related_space_ids(space_id):
    """S itself, every ancestor of S, and every descendant of S."""
    ids = {space_id}
    ids.update(ancestor_ids(space_id))
    ids.update(descendant_ids(space_id))
    return ids


def self_and_descendant_ids(space_id):
    ids = {space_id}
    ids.update(descendant_ids(space_id))
    return ids


def self_and_ancestor_ids(space_id):
    ids = {space_id}
    ids.update(ancestor_ids(space_id))
    return ids


# --------------------------------------------------------------------------
# convenience collections
# --------------------------------------------------------------------------
def bookings_of_client(client_id):
    return [b for b in db.bookings.rows() if b["client_id"] == client_id]


def holds_of_booking(booking_id):
    return [h for h in db.holds.rows() if h["booking_id"] == booking_id]


def licenses_of_booking(booking_id):
    return [l for l in db.licenses.rows() if l["booking_id"] == booking_id]


def service_orders_of_booking(booking_id):
    return [o for o in db.service_orders.rows() if o["booking_id"] == booking_id]


def labor_calls_of_booking(booking_id):
    return [c for c in db.labor_calls.rows() if c["booking_id"] == booking_id]


def catering_of_booking(booking_id):
    return [c for c in db.caterings.rows() if c["booking_id"] == booking_id]


def usage_records_of_booking(booking_id):
    return [u for u in db.usage_records.rows() if u["booking_id"] == booking_id]


def settlements_of_booking(booking_id):
    return [s for s in db.settlements.rows() if s["booking_id"] == booking_id]


def line_items_of_settlement(settlement_id):
    return [l for l in db.line_items.rows() if l["settlement_id"] == settlement_id]


def labor_calls_of_jurisdiction(jurisdiction_id):
    return [c for c in db.labor_calls.rows() if c["jurisdiction_id"] == jurisdiction_id]


def policy_window_for_class(event_class):
    for window in db.policy_windows.rows():
        if window["event_class"] == event_class:
            return window
    return None


def live_license_of_booking(booking_id):
    """The single non-terminal license of a booking, if any."""
    for lic in licenses_of_booking(booking_id):
        if lic["status"] in ("DRAFT", "ISSUED", "EXECUTED", "AMENDMENT_PENDING"):
            return lic
    return None


def deposit_license_of_booking(booking_id):
    """The license whose escrow a settlement finalization draws down."""
    live = live_license_of_booking(booking_id)
    if live is not None:
        return live
    holders = [l for l in licenses_of_booking(booking_id) if l.get("deposit_held_cents")]
    if holders:
        return holders[-1]
    rows = licenses_of_booking(booking_id)
    return rows[-1] if rows else None
