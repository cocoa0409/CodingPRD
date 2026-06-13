"""Existence lookups and optimistic-concurrency checks.

Existence failures raise ERR_NOT_FOUND (404). Path identifiers are resolved
before body foreign keys (PRD §2.6).
"""
import db
from errors import ApiError


def _get_or_404(store, ident):
    rec = store.get(ident)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Resource not found")
    return rec


def get_artist(ident):
    return _get_or_404(db.artists, ident)


def get_client(ident):
    return _get_or_404(db.clients, ident)


def get_flash(ident):
    return _get_or_404(db.flash_designs, ident)


def get_custom_request(ident):
    return _get_or_404(db.custom_requests, ident)


def get_appointment(ident):
    return _get_or_404(db.appointments, ident)


def get_chair(ident):
    return _get_or_404(db.chairs, ident)


def get_deposit(ident):
    return _get_or_404(db.deposits, ident)


def get_touchup(ident):
    return _get_or_404(db.touchups, ident)


def get_portfolio_item(ident):
    return _get_or_404(db.portfolio_items, ident)


def check_version(record, expected):
    """OCC check (PRD §2.7). When expected is provided, it must equal the
    record's current version, else ERR_STALE_VERSION (412)."""
    if expected is None:
        return
    if record.get("version") != expected:
        raise ApiError("ERR_STALE_VERSION",
                       "Stale version: expected %s, current %s"
                       % (expected, record.get("version")))
