"""Blueprint registry."""

from flask import Blueprint


def make_blueprint(name):
    return Blueprint(name, __name__)


from . import (  # noqa: E402,F401
    clients,
    records,
    alerts,
    matters,
    deadlines,
    letters,
    takedowns,
    agreements,
    evidence,
    filings,
    searches,
    recordations,
    referrals,
    clock,
)

ALL_BLUEPRINTS = [
    clients.bp,
    records.bp,
    alerts.bp,
    matters.bp,
    deadlines.bp,
    letters.bp,
    takedowns.bp,
    agreements.bp,
    evidence.bp,
    filings.bp,
    searches.bp,
    recordations.bp,
    referrals.bp,
    clock.bp,
]
