"""Helpers shared by the route modules."""
from flask import request

import store
from errors import ApiError

E = "ERR_INVALID_REQUEST"


def qint(name):
    """Optional integer query-string filter."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = raw.strip()
    digits = text[1:] if text.startswith("-") or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError(E, "%s must be an integer" % name)
    return int(text)


def qstr(name, allowed=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    value = raw.strip()
    if allowed is not None and value not in allowed:
        raise ApiError(E, "%s is not a recognised value" % name)
    return value


def match(rec, **filters):
    for key, val in filters.items():
        if val is None:
            continue
        if rec.get(key) != val:
            return False
    return True


def permit_of(rec):
    return store.get("permits", rec["permit_id"])


def owning_outfitter_of_permit(permit):
    return permit["outfitter_id"] if permit else None
