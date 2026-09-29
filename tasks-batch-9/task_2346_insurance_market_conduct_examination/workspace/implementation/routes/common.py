"""Small shared helpers for the route modules (query filters)."""

from flask import request


def str_query(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_query(name):
    """A boolean query filter; anything unrecognised is treated as absent."""
    value = str_query(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def filter_equals(rows, field, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(field) == value]
