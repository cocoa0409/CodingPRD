"""Path-identifier and body-reference resolution (PRD 2.10, precedence 3 and 4)."""

from db import store
from errors import fail

_PATH_ERRORS = {
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "crew_bases": "ERR_CREW_BASE_NOT_FOUND",
    "aircraft": "ERR_AIRCRAFT_NOT_FOUND",
    "pilots": "ERR_PILOT_NOT_FOUND",
    "schedule_cycles": "ERR_SCHEDULE_CYCLE_NOT_FOUND",
    "flight_legs": "ERR_FLIGHT_LEG_NOT_FOUND",
    "cancellation_claims": "ERR_CANCELLATION_CLAIM_NOT_FOUND",
    "passthrough_claims": "ERR_PASSTHROUGH_CLAIM_NOT_FOUND",
    "scorecards": "ERR_SCORECARD_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "brand_audits": "ERR_BRAND_AUDIT_NOT_FOUND",
    "negotiations": "ERR_NEGOTIATION_NOT_FOUND",
}


def _get(collection_name, identifier):
    collection = getattr(store, collection_name)
    entity = collection.get(identifier)
    if entity is None:
        fail(_PATH_ERRORS[collection_name])
    return entity


def agreement(identifier):
    return _get("agreements", identifier)


def crew_base(identifier):
    return _get("crew_bases", identifier)


def aircraft(identifier):
    return _get("aircraft", identifier)


def pilot(identifier):
    return _get("pilots", identifier)


def schedule_cycle(identifier):
    return _get("schedule_cycles", identifier)


def flight_leg(identifier):
    return _get("flight_legs", identifier)


def cancellation_claim(identifier):
    return _get("cancellation_claims", identifier)


def passthrough_claim(identifier):
    return _get("passthrough_claims", identifier)


def scorecard(identifier):
    return _get("scorecards", identifier)


def invoice(identifier):
    return _get("invoices", identifier)


def brand_audit(identifier):
    return _get("brand_audits", identifier)


def negotiation(identifier):
    return _get("negotiations", identifier)


def reference(collection_name, identifier):
    """Body foreign key resolution: a miss is always ERR_REFERENCE_NOT_FOUND."""
    collection = getattr(store, collection_name)
    if not isinstance(identifier, str):
        fail("ERR_REFERENCE_NOT_FOUND")
    entity = collection.get(identifier)
    if entity is None:
        fail("ERR_REFERENCE_NOT_FOUND")
    return entity
