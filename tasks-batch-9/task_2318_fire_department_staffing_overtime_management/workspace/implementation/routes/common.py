"""Shared list-filter and ordering helpers (PRD 2.3)."""

from flask import request

from store import db, order_key


def f(field):
    return lambda entity: entity.get(field)


def apply_filters(items, mapping):
    for param, getter in mapping.items():
        if param not in request.args:
            continue
        wanted = request.args.get(param)
        items = [e for e in items if _eq(getter(e), wanted)]
    return items


def _eq(value, wanted):
    if value is None:
        return False
    if isinstance(value, bool):
        return ("true" if value else "false") == str(wanted).strip().lower()
    return str(value) == str(wanted)


def shift_date_of(entity):
    shift = db.duty_shifts.get(entity.get("duty_shift_id"))
    return shift["shift_date"] if shift else ""


def closure_priority_of(entity):
    unit = db.apparatus.get(entity.get("apparatus_id"))
    return unit["closure_priority"] if unit else 0


def nulls_last(value):
    return (1, 0) if value is None else (0, value)


def sorted_by(items, key):
    return sorted(items, key=lambda e: tuple(key(e)) + order_key(e))
