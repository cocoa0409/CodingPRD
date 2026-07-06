"""Existence lookups (PRD §2.9): each returns the entity or raises the matching
not-found error. References are checked left-to-right by the caller."""
from db import store
from errors import (
    err,
    ERR_SEASON_NOT_FOUND,
    ERR_PRODUCTION_NOT_FOUND,
    ERR_PERFORMANCE_NOT_FOUND,
    ERR_VENUE_NOT_FOUND,
    ERR_SEAT_NOT_FOUND,
    ERR_PATRON_NOT_FOUND,
    ERR_SUBSCRIPTION_NOT_FOUND,
    ERR_TICKET_NOT_FOUND,
    ERR_DONATION_NOT_FOUND,
    ERR_EXCHANGE_NOT_FOUND,
    ERR_AUDITION_NOT_FOUND,
)


def get_season(sid):
    o = store.seasons.get(sid)
    if o is None:
        raise err(ERR_SEASON_NOT_FOUND)
    return o


def get_production(pid):
    o = store.productions.get(pid)
    if o is None:
        raise err(ERR_PRODUCTION_NOT_FOUND)
    return o


def get_performance(pid):
    o = store.performances.get(pid)
    if o is None:
        raise err(ERR_PERFORMANCE_NOT_FOUND)
    return o


def get_venue(vid):
    o = store.venues.get(vid)
    if o is None:
        raise err(ERR_VENUE_NOT_FOUND)
    return o


def get_seat(sid):
    o = store.seats.get(sid)
    if o is None:
        raise err(ERR_SEAT_NOT_FOUND)
    return o


def get_patron(pid):
    o = store.patrons.get(pid)
    if o is None:
        raise err(ERR_PATRON_NOT_FOUND)
    return o


def get_subscription(sid):
    o = store.subscriptions.get(sid)
    if o is None:
        raise err(ERR_SUBSCRIPTION_NOT_FOUND)
    return o


def get_ticket(tid):
    o = store.tickets.get(tid)
    if o is None:
        raise err(ERR_TICKET_NOT_FOUND)
    return o


def get_donation(did):
    o = store.donations.get(did)
    if o is None:
        raise err(ERR_DONATION_NOT_FOUND)
    return o


def get_exchange(eid):
    o = store.exchanges.get(eid)
    if o is None:
        raise err(ERR_EXCHANGE_NOT_FOUND)
    return o


def get_audition(aid):
    o = store.auditions.get(aid)
    if o is None:
        raise err(ERR_AUDITION_NOT_FOUND)
    return o
