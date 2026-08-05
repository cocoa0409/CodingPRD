"""Ladder step 3: existence lookups, validated left to right (PRD 2.5)."""

import envelope
import store
from errors import ApiError


def _get(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def zone(zone_id):
    return _get(store.zones, zone_id, "ERR_ZONE_NOT_FOUND")


def owner(owner_id):
    return _get(store.owners, owner_id, "ERR_OWNER_NOT_FOUND")


def prop(property_id):
    return _get(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")


def officer(officer_id):
    return _get(store.officers, officer_id, "ERR_OFFICER_NOT_FOUND")


def complaint(complaint_id):
    return _get(store.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")


def inspection(inspection_id):
    return _get(store.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")


def order(order_id):
    return _get(store.orders, order_id, "ERR_ORDER_NOT_FOUND")


def notice(notice_id):
    return _get(store.notices, notice_id, "ERR_NOTICE_NOT_FOUND")


def station(station_id):
    return _get(store.stations, station_id, "ERR_STATION_NOT_FOUND")


def invoice(invoice_id):
    return _get(store.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")


def page(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return envelope.arr([serializer(r) for r in window], limit, offset, total)
