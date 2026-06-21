"""Existence lookups (priority 4: ERR_NOT_FOUND)."""
from db import db
from errors import err, ERR_NOT_FOUND


def get_unit(unit_id):
    u = db.cold_storage_units.get(unit_id)
    if u is None:
        raise err(ERR_NOT_FOUND, "Cold storage unit not found.")
    return u


def get_lot(lot_id):
    l = db.inventory_lots.get(lot_id)
    if l is None:
        raise err(ERR_NOT_FOUND, "Inventory lot not found.")
    return l


def get_agency(agency_id):
    a = db.agencies.get(agency_id)
    if a is None:
        raise err(ERR_NOT_FOUND, "Agency not found.")
    return a


def get_cycle(cycle_id):
    c = db.allocation_cycles.get(cycle_id)
    if c is None:
        raise err(ERR_NOT_FOUND, "Allocation cycle not found.")
    return c


def get_order(order_id):
    o = db.agency_orders.get(order_id)
    if o is None:
        raise err(ERR_NOT_FOUND, "Agency order not found.")
    return o


def get_household(household_id):
    h = db.client_households.get(household_id)
    if h is None:
        raise err(ERR_NOT_FOUND, "Client household not found.")
    return h


def get_event(event_id):
    e = db.distribution_events.get(event_id)
    if e is None:
        raise err(ERR_NOT_FOUND, "Distribution event not found.")
    return e
