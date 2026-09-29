"""Shared route helpers: existence resolution (ladder step 5) and list paging."""
from errors import (
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_BLOCK_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_BUILD_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_COMPONENT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_HOST_NOT_FOUND,
    ERR_INSTALLMENT_NOT_FOUND,
    ERR_PACKAGE_NOT_FOUND,
    ERR_RIGHTS_DEAL_NOT_FOUND,
    ERR_TRANCHE_NOT_FOUND,
    fail,
)
from response import list_response
from store import db
from validation import paginate, pagination, query_filter


def _lookup(collection, record_id, error_spec, label):
    record = None
    if isinstance(record_id, str):
        record = collection.get(record_id)
    if record is None:
        fail(error_spec, "%s %s was not found." % (label, record_id))
    return record


def get_event(record_id):
    return _lookup(db.events, record_id, ERR_EVENT_NOT_FOUND, "Event")


def get_deal(record_id):
    return _lookup(db.rights_deals, record_id, ERR_RIGHTS_DEAL_NOT_FOUND, "Rights deal")


def get_tranche(record_id):
    return _lookup(db.release_tranches, record_id, ERR_TRANCHE_NOT_FOUND, "Release tranche")


def get_block(record_id):
    return _lookup(db.allocation_blocks, record_id, ERR_BLOCK_NOT_FOUND, "Allocation block")


def get_package(record_id):
    return _lookup(db.package_products, record_id, ERR_PACKAGE_NOT_FOUND, "Package")


def get_component(record_id):
    return _lookup(db.package_components, record_id, ERR_COMPONENT_NOT_FOUND, "Package component")


def get_client(record_id):
    return _lookup(db.clients, record_id, ERR_CLIENT_NOT_FOUND, "Client")


def get_booking(record_id):
    return _lookup(db.bookings, record_id, ERR_BOOKING_NOT_FOUND, "Booking")


def get_installment(record_id):
    return _lookup(db.payment_installments, record_id, ERR_INSTALLMENT_NOT_FOUND, "Installment")


def get_build(record_id):
    return _lookup(db.hospitality_builds, record_id, ERR_BUILD_NOT_FOUND, "Hospitality build")


def get_host(record_id):
    return _lookup(db.on_site_hosts, record_id, ERR_HOST_NOT_FOUND, "On-site host")


def get_assignment(record_id):
    return _lookup(db.host_assignments, record_id, ERR_ASSIGNMENT_NOT_FOUND, "Host assignment")


def filtered(records, filters):
    """Apply the endpoint's optional equality filters conjunctively (PRD 2.3)."""
    out = records
    for field, value in filters:
        if value is None:
            continue
        out = [r for r in out if r.get(field) == value]
    return out


def listing(records, serializer, filters=()):
    limit, offset = pagination()
    pairs = []
    for field in filters:
        pairs.append((field, query_filter(field)))
    rows = filtered(records, pairs)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return list_response([serializer(r) for r in page], limit, offset, total)
