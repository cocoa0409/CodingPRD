"""Request-shape validation (ladder rung 3) and reference resolution (rungs 4/5).

Every failure in this module is ERR_INVALID_REQUEST (422) except the existence
helpers, which raise the not-found identifier their reference class declares.
"""
from flask import request

import clock
from dates import parse_iso
from db import db
from errors import ApiError

MISSING = object()

CANONICAL_CLAUSE_ORDER = [
    "REGISTRATION_DISCLOSURE",
    "FINANCIAL_STATEMENT_AVAILABILITY",
    "PAID_SOLICITOR_IDENTITY",
    "TAX_DEDUCTIBILITY",
    "PERCENT_TO_CHARITY",
]

SOLICITATION_CHANNELS = [
    "MAIL", "PHONE", "EMAIL", "WEB_PASSIVE", "WEB_TARGETED", "EVENT", "GRANT_REQUEST",
]


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body(required=True):
    """Read the JSON request body as a dict."""
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        payload = None
    if payload is None:
        if required:
            if request.data and request.data.strip():
                _bad("Request body must be a JSON object.")
            payload = {}
        else:
            payload = {}
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


# --------------------------------------------------------------------------
# scalar readers
# --------------------------------------------------------------------------
def req_string(body, name, min_len=1, max_len=None, allow_blank=False):
    if name not in body or body[name] is None:
        _bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if not allow_blank and not value.strip():
        _bad("%s may not be blank." % name)
    if min_len is not None and len(value) < min_len:
        _bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s may be at most %d characters." % (name, max_len))
    return value


def opt_string(body, name, default=None, max_len=None, allow_blank=True):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if not allow_blank and not value.strip():
        _bad("%s may not be blank." % name)
    if max_len is not None and len(value) > max_len:
        _bad("%s may be at most %d characters." % (name, max_len))
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        _bad("%s is required." % name)
    value = _as_int(name, body[name])
    if minimum is not None and value < minimum:
        _bad("%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s may not be larger than %d." % (name, maximum))
    return value


def opt_int(body, name, default=0, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_number(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        _bad("%s is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("%s must be a number." % name)
    if minimum is not None and value < minimum:
        _bad("%s may not be smaller than %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s may not be larger than %s." % (name, maximum))
    return value


def opt_number(body, name, default=0, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return req_number(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    if name not in body or body[name] is None:
        _bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % name)
    return value


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def req_datetime(body, name):
    if name not in body or body[name] is None:
        _bad("%s is required." % name)
    value = body[name]
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        _bad("%s must be a parseable ISO 8601 datetime." % name)
    return parsed


def req_array(body, name, allowed=None, non_empty=True):
    if name not in body or body[name] is None:
        _bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, list):
        _bad("%s must be an array." % name)
    if non_empty and not value:
        _bad("%s may not be empty." % name)
    for element in value:
        if not isinstance(element, str):
            _bad("%s must contain only strings." % name)
        if allowed is not None and element not in allowed:
            _bad("%s contains an unsupported value: %s" % (name, element))
    return value


def opt_array(body, name, allowed=None, default=None):
    if name not in body or body[name] is None:
        return list(default) if default is not None else []
    return req_array(body, name, allowed=allowed, non_empty=False)


def req_state_code(body, name):
    """Two uppercase letters -- shape only; existence is ladder rung 5."""
    value = req_string(body, name)
    if len(value) != 2 or not value.isalpha() or not value.isupper():
        _bad("%s must be exactly two uppercase letters." % name)
    return value


# --------------------------------------------------------------------------
# existence resolution -- ladder rungs 4 (path) and 5 (payload foreign keys)
# --------------------------------------------------------------------------
def find_organization(organization_id):
    row = db.organizations.get(organization_id)
    if row is None:
        raise ApiError("ERR_ORGANIZATION_NOT_FOUND")
    return row


def find_state_profile(state_code):
    row = db.state_profiles.get(state_code)
    if row is None:
        raise ApiError("ERR_STATE_PROFILE_NOT_FOUND")
    return row


def find_financial_statement(statement_id):
    row = db.financial_statements.get(statement_id)
    if row is None:
        raise ApiError("ERR_FINANCIAL_STATEMENT_NOT_FOUND")
    return row


def find_officer(officer_id):
    row = db.officer_disclosures.get(officer_id)
    if row is None:
        raise ApiError("ERR_OFFICER_NOT_FOUND")
    return row


def find_registration(registration_id):
    row = db.state_registrations.get(registration_id)
    if row is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND")
    return row


def find_registration_document(document_id):
    row = db.registration_documents.get(document_id)
    if row is None:
        raise ApiError("ERR_REGISTRATION_DOCUMENT_NOT_FOUND")
    return row


def find_extension_request(request_id):
    row = db.extension_requests.get(request_id)
    if row is None:
        raise ApiError("ERR_EXTENSION_REQUEST_NOT_FOUND")
    return row


def find_fundraiser(fundraiser_id):
    row = db.professional_fundraisers.get(fundraiser_id)
    if row is None:
        raise ApiError("ERR_FUNDRAISER_NOT_FOUND")
    return row


def find_contract(contract_id):
    row = db.fundraising_contracts.get(contract_id)
    if row is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return row


def find_promotion(promotion_id):
    row = db.coventure_promotions.get(promotion_id)
    if row is None:
        raise ApiError("ERR_PROMOTION_NOT_FOUND")
    return row


def find_enforcement_action(action_id):
    row = db.enforcement_actions.get(action_id)
    if row is None:
        raise ApiError("ERR_ENFORCEMENT_ACTION_NOT_FOUND")
    return row


def resolve_state_codes(state_codes):
    """Resolve every element of a state_codes array, left to right."""
    return [find_state_profile(code) for code in state_codes]
