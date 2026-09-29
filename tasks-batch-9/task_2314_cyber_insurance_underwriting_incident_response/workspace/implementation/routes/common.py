"""Shared query-filter helpers for list endpoints."""

from flask import request

from errors import bad_request


def filter_value(name, domain=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if domain is not None and raw not in domain:
        raise bad_request("%s must be one of %s" % (name, ", ".join(sorted(domain))))
    return raw


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("%s must be a boolean" % name)


def apply_eq(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]
