"""Shared route plumbing: body parsing and existence lookups (PRD §2.5, §2.6)."""
from flask import request

import db
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, err


def get_body():
    """Parse the JSON request body, tolerating an empty body as {}.

    A present-but-malformed body is rejected with ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def must_exist(collection, resource_id, label):
    """Resolve an id to an existing record or raise ERR_NOT_FOUND (PRD §2.5)."""
    rec = collection.get(resource_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, f"{label} not found")
    return rec


def get_reservation(reservation_id):
    return must_exist(db.reservations, reservation_id, "Reservation")
