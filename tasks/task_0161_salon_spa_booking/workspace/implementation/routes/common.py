"""Shared per-route helpers: auth+RBAC entry, body parsing, list filtering."""
from flask import request

from errors import err
from middleware import authenticate, require_roles
from util import public, paginate

ALL_ROLES = ("SalonOwner", "FrontDesk", "Stylist", "Client")


def auth(allowed):
    """Authenticate then enforce RBAC in one step. Returns the Caller."""
    caller = authenticate()
    require_roles(caller, allowed)
    return caller


def json_body():
    """Parse the JSON request body, tolerating an empty body as {}.

    A present-but-malformed body raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def list_response(collection, predicate):
    """Filter a collection by predicate, paginate, and return an envelope payload."""
    items = [o for o in collection.values() if predicate(o)]
    page, meta = paginate(items, request.args)
    return page, meta
