"""Rank 4 of the rejection ladder: existence lookups (the 404 family)."""
import db
import errors
from errors import fail


def _get(collection, identifier, error_id):
    if not isinstance(identifier, str):
        fail(errors.ERR_INVALID_REQUEST, "Identifier must be a string.")
    record = collection.get(identifier)
    if record is None:
        fail(error_id)
    return record


def get_store(store_id):
    return _get(db.stores, store_id, errors.ERR_STORE_NOT_FOUND)


def get_channel(channel_id):
    return _get(db.channels, channel_id, errors.ERR_CHANNEL_NOT_FOUND)


def get_menu_version(version_id):
    return _get(db.menu_versions, version_id, errors.ERR_MENU_VERSION_NOT_FOUND)


def get_menu_item(item_id):
    return _get(db.menu_items, item_id, errors.ERR_MENU_ITEM_NOT_FOUND)


def get_listing(listing_id):
    return _get(db.listings, listing_id, errors.ERR_LISTING_NOT_FOUND)


def get_availability_event(event_id):
    return _get(db.availability_events, event_id,
                errors.ERR_AVAILABILITY_EVENT_NOT_FOUND)


def get_order(order_id):
    return _get(db.orders, order_id, errors.ERR_ORDER_NOT_FOUND)


def get_courier_network(network_id):
    return _get(db.courier_networks, network_id, errors.ERR_COURIER_NETWORK_NOT_FOUND)


def get_assignment(assignment_id):
    return _get(db.assignments, assignment_id, errors.ERR_ASSIGNMENT_NOT_FOUND)


def get_adjustment(adjustment_id):
    return _get(db.adjustments, adjustment_id, errors.ERR_ADJUSTMENT_NOT_FOUND)


def get_statement(statement_id):
    return _get(db.statements, statement_id, errors.ERR_STATEMENT_NOT_FOUND)
