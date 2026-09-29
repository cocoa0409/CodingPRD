"""Path and body foreign-key resolution. Each collection carries its own not-found code."""
from db import store
from errors import ApiError


def _find(collection, identifier, error_id):
    if not isinstance(identifier, str) or identifier == "":
        raise ApiError(error_id)
    row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def project(identifier):
    return _find(store.projects, identifier, "ERR_PROJECT_NOT_FOUND")


def policy(identifier):
    return _find(store.policies, identifier, "ERR_POLICY_NOT_FOUND")


def coverage_part(identifier):
    return _find(store.coverage_parts, identifier, "ERR_COVERAGE_PART_NOT_FOUND")


def interest(identifier):
    return _find(store.interests, identifier, "ERR_INTEREST_NOT_FOUND")


def endorsement(identifier):
    return _find(store.endorsements, identifier, "ERR_ENDORSEMENT_NOT_FOUND")


def claim(identifier):
    return _find(store.claims, identifier, "ERR_CLAIM_NOT_FOUND")


def payment(identifier):
    return _find(store.payments, identifier, "ERR_PAYMENT_NOT_FOUND")


def notice(identifier):
    return _find(store.notices, identifier, "ERR_NOTICE_NOT_FOUND")


def facility(identifier):
    return _find(store.facilities, identifier, "ERR_FACILITY_NOT_FOUND")


def assignment(identifier):
    return _find(store.assignments, identifier, "ERR_ASSIGNMENT_NOT_FOUND")


def fk_project(payload):
    identifier = payload.get("project_id")
    if identifier is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'project_id' is required.")
    return project(identifier)


def fk_policy(payload):
    identifier = payload.get("policy_id")
    if identifier is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'policy_id' is required.")
    return policy(identifier)


def fk_facility(payload):
    identifier = payload.get("facility_id")
    if identifier is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'facility_id' is required.")
    return facility(identifier)


def fk_claim(payload):
    identifier = payload.get("claim_id")
    if identifier is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'claim_id' is required.")
    return claim(identifier)


def fk_interest(payload):
    identifier = payload.get("payee_interest_id")
    if identifier is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'payee_interest_id' is required.")
    return interest(identifier)
