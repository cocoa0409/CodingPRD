"""Path/body identifier resolution (PRD section 2.9, steps 5 and 6)."""

from errors import ApiError
from store import store


def _find(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def find_space(identifier, error_id="ERR_SPACE_NOT_FOUND"):
    return _find(store.spaces, identifier, error_id)


def find_artist(identifier, error_id="ERR_PARTY_NOT_FOUND"):
    return _find(store.artists, identifier, error_id)


def find_client(identifier, error_id="ERR_PARTY_NOT_FOUND"):
    return _find(store.clients, identifier, error_id)


def find_department(identifier, error_id="ERR_DEPARTMENT_NOT_FOUND"):
    return _find(store.departments, identifier, error_id)


def find_equipment(identifier, error_id="ERR_EQUIPMENT_ITEM_NOT_FOUND"):
    return _find(store.equipment, identifier, error_id)


def find_engagement(identifier, error_id="ERR_ENGAGEMENT_NOT_FOUND"):
    return _find(store.engagements, identifier, error_id)


def find_negotiation(identifier):
    return _find(store.negotiations, identifier, "ERR_NEGOTIATION_NOT_FOUND")


def find_rider(identifier):
    return _find(store.riders, identifier, "ERR_TECH_RIDER_NOT_FOUND")


def find_call(identifier):
    return _find(store.calls, identifier, "ERR_LABOR_CALL_NOT_FOUND")


def find_tier(identifier):
    return _find(store.tiers, identifier, "ERR_PRICE_TIER_NOT_FOUND")


def find_package(identifier):
    return _find(store.packages, identifier, "ERR_SUBSCRIPTION_PACKAGE_NOT_FOUND")


def find_settlement(identifier):
    return _find(store.settlements, identifier, "ERR_SETTLEMENT_NOT_FOUND")


def engagement_space(engagement):
    return store.spaces.get(engagement["space_id"])
