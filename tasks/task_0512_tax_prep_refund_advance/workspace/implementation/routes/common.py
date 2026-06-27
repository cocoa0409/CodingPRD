"""Shared route helpers: body parsing, pagination, existence lookups.

Validation ordering (PRD §2.5): auth (401) -> authz (403) -> existence (404)
-> well-formedness (422) -> state (409) -> OCC (412) -> business rules. Routes
call these in that order."""
from flask import request

import errors
from db import db


def get_json_body():
    """Parse the JSON body; tolerate an empty body as {}."""
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def paginate(query_args=None):
    """Parse limit/offset (PRD §2.3). limit default 10 (min 1, max 100);
    offset default 0 (min 0). Out-of-range values clamp into range."""
    args = query_args if query_args is not None else request.args
    limit = _parse_int(args.get("limit"), 10)
    offset = _parse_int(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int(val, default):
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def page_slice(items, limit, offset):
    """Sort by creation order (created_at asc, PRD §2.3) then slice.
    Returns (page_items, total_count)."""
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    return ordered[offset:offset + limit], total


def require_found(record):
    if record is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found")
    return record


def get_office(office_id):
    return require_found(db.offices.get(office_id))


def get_credential(credential_id):
    return require_found(db.credentials.get(credential_id))


def get_preparer(preparer_id):
    return require_found(db.preparers.get(preparer_id))


def get_client(client_id):
    return require_found(db.clients.get(client_id))


def get_appointment(appointment_id):
    return require_found(db.appointments.get(appointment_id))


def get_return(return_id):
    return require_found(db.returns.get(return_id))


def get_document(document_id):
    return require_found(db.documents.get(document_id))


def get_audit_protection(ap_id):
    return require_found(db.audit_protections.get(ap_id))


def get_refund_transfer(rt_id):
    return require_found(db.refund_transfers.get(rt_id))


def get_refund_advance(ra_id):
    return require_found(db.refund_advances.get(ra_id))
