"""Shared helpers for the route modules: path resolution and list handling."""

from flask import request

import response
from db import db, ordered
from errors import ApiError

_SENTINEL = object()


def _resolve(store, identifier, error_id):
    record = store.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def get_venue(identifier):
    return _resolve(db.venues, identifier, "ERR_VENUE_NOT_FOUND")


def get_member(identifier):
    return _resolve(db.members, identifier, "ERR_MEMBER_NOT_FOUND")


def get_pool(identifier):
    return _resolve(db.revenue_pools, identifier, "ERR_REVENUE_POOL_NOT_FOUND")


def get_run(identifier):
    return _resolve(db.distribution_runs, identifier, "ERR_DISTRIBUTION_RUN_NOT_FOUND")


def get_appearance(identifier):
    return _resolve(db.bowl_appearances, identifier, "ERR_BOWL_APPEARANCE_NOT_FOUND")


def get_action(identifier):
    return _resolve(db.membership_actions, identifier, "ERR_MEMBERSHIP_ACTION_NOT_FOUND")


def get_proposal(identifier):
    return _resolve(db.budget_proposals, identifier, "ERR_BUDGET_PROPOSAL_NOT_FOUND")


def get_rivalry(identifier):
    return _resolve(db.protected_rivalries, identifier, "ERR_PROTECTED_RIVALRY_NOT_FOUND")


def get_game(identifier):
    return _resolve(db.schedule_games, identifier, "ERR_SCHEDULE_GAME_NOT_FOUND")


def get_event(identifier):
    return _resolve(db.championship_events, identifier, "ERR_CHAMPIONSHIP_EVENT_NOT_FOUND")


def get_report(identifier):
    return _resolve(db.audit_reports, identifier, "ERR_AUDIT_REPORT_NOT_FOUND")


def string_filter(field):
    """Return the raw query value for an equality filter, or None."""
    value = request.args.get(field)
    if value is None or value == "":
        return None
    return value


def int_filter(field):
    """An integer equality filter; an unparseable value matches nothing."""
    raw = request.args.get(field)
    if raw is None or raw == "":
        return None
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return _SENTINEL


def bool_filter(field):
    raw = request.args.get(field)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return _SENTINEL


def matches(record, criteria):
    """criteria maps a record field to a filter value; None means "unfiltered"."""
    for field, expected in criteria.items():
        if expected is None:
            continue
        if expected is _SENTINEL:
            return False
        if record.get(field) != expected:
            return False
    return True


def listing(records, serializer, criteria=None, presorted=False):
    """Apply filters, pagination bounds and the standard list envelope."""
    limit, offset = response.pagination()
    if criteria:
        records = [record for record in records if matches(record, criteria)]
    if not presorted:
        records = ordered(records)
    window, total = response.paginate(records, limit, offset)
    return response.collection(
        [serializer(record) for record in window], limit, offset, total
    )
