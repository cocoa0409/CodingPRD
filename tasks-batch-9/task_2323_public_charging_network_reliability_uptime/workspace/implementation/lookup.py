"""Identifier resolution (PRD §2.5): path segments left to right, then body
foreign keys in declaration order.  Each miss raises that identifier's own 404.
"""
import db
from errors import err


def _find(store, identifier, error_id):
    if not isinstance(identifier, str):
        raise err(error_id)
    row = store.get(identifier)
    if row is None:
        raise err(error_id)
    return row


def host_site(identifier):
    return _find(db.host_sites, identifier, "ERR_HOST_SITE_NOT_FOUND")


def station(identifier):
    return _find(db.stations, identifier, "ERR_STATION_NOT_FOUND")


def port(identifier):
    return _find(db.ports, identifier, "ERR_PORT_NOT_FOUND")


def outage(identifier):
    return _find(db.outages, identifier, "ERR_OUTAGE_NOT_FOUND")


def dispatch(identifier):
    return _find(db.dispatches, identifier, "ERR_DISPATCH_NOT_FOUND")


def spare_part(identifier):
    return _find(db.spare_parts, identifier, "ERR_SPARE_PART_NOT_FOUND")


def reservation(identifier):
    return _find(db.reservations, identifier, "ERR_RESERVATION_NOT_FOUND")


def uptime_report(identifier):
    return _find(db.reports, identifier, "ERR_UPTIME_REPORT_NOT_FOUND")


def claim(identifier):
    return _find(db.claims, identifier, "ERR_CLAIM_NOT_FOUND")


def complaint(identifier):
    return _find(db.complaints, identifier, "ERR_COMPLAINT_NOT_FOUND")
