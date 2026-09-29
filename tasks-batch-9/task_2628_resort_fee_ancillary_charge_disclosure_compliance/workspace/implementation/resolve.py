"""Identifier resolution. Ranks 6 (path, left to right) and 8 (body references)."""

import store
from errors import ApiError

_TABLES = {
    "jurisdiction": (lambda: store.jurisdictions, "ERR_JURISDICTION_NOT_FOUND"),
    "taxability_rule": (lambda: store.taxability_rules, "ERR_TAXABILITY_RULE_NOT_FOUND"),
    "property": (lambda: store.properties, "ERR_PROPERTY_NOT_FOUND"),
    "channel": (lambda: store.channels, "ERR_CHANNEL_NOT_FOUND"),
    "fee_program": (lambda: store.fee_programs, "ERR_FEE_PROGRAM_NOT_FOUND"),
    "fee": (lambda: store.fees, "ERR_FEE_NOT_FOUND"),
    "profile": (lambda: store.profiles, "ERR_PROFILE_NOT_FOUND"),
    "booking": (lambda: store.bookings, "ERR_BOOKING_NOT_FOUND"),
    "folio": (lambda: store.folios, "ERR_FOLIO_NOT_FOUND"),
    "folio_line": (lambda: store.folio_lines, "ERR_FOLIO_LINE_NOT_FOUND"),
    "opt_out_request": (lambda: store.opt_out_requests, "ERR_OPT_OUT_REQUEST_NOT_FOUND"),
    "complaint": (lambda: store.complaints, "ERR_COMPLAINT_NOT_FOUND"),
    "inquiry": (lambda: store.inquiries, "ERR_INQUIRY_NOT_FOUND"),
    "revenue_model": (lambda: store.revenue_models, "ERR_REVENUE_MODEL_NOT_FOUND"),
}


def get(kind, identifier):
    table, error_id = _TABLES[kind]
    row = table().get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, "No %s with id %r." % (kind.replace("_", " "), identifier))
    return row


def peek(kind, identifier):
    table, _ = _TABLES[kind]
    if not isinstance(identifier, str):
        return None
    return table().get(identifier)


def jurisdiction(identifier):
    return get("jurisdiction", identifier)


def taxability_rule(identifier):
    return get("taxability_rule", identifier)


def property_(identifier):
    return get("property", identifier)


def channel(identifier):
    return get("channel", identifier)


def fee_program(identifier):
    return get("fee_program", identifier)


def fee(identifier):
    return get("fee", identifier)


def profile(identifier):
    return get("profile", identifier)


def booking(identifier):
    return get("booking", identifier)


def folio(identifier):
    return get("folio", identifier)


def folio_line(identifier):
    return get("folio_line", identifier)


def opt_out_request(identifier):
    return get("opt_out_request", identifier)


def complaint(identifier):
    return get("complaint", identifier)


def inquiry(identifier):
    return get("inquiry", identifier)


def revenue_model(identifier):
    return get("revenue_model", identifier)
