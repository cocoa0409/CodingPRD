"""Existence lookups that raise ERR_NOT_FOUND (404) when missing (PRD §2.6)."""
import db
import errors
from errors import ApiError


def _get(table, ident):
    rec = table.get(ident)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Referenced resource does not exist.")
    return rec


def venue(ident):
    return _get(db.venues, ident)


def attraction(ident):
    return _get(db.attractions, ident)


def time_slot(ident):
    return _get(db.time_slots, ident)


def pricing_rule(ident):
    return _get(db.pricing_rules, ident)


def guest(ident):
    return _get(db.guests, ident)


def waiver(ident):
    return _get(db.waivers, ident)


def reservation(ident):
    return _get(db.reservations, ident)


def ticket(ident):
    return _get(db.tickets, ident)


def pass_product(ident):
    return _get(db.pass_products, ident)


def issued_pass(ident):
    return _get(db.passes, ident)


def scare_zone(ident):
    return _get(db.scare_zones, ident)


def actor_shift(ident):
    return _get(db.actor_shifts, ident)


def closure(ident):
    return _get(db.closures, ident)
