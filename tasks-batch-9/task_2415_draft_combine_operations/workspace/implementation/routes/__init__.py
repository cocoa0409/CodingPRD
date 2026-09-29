"""Blueprint registry. Every /draft-ops blueprint is mounted under the API
prefix; the logical clock lives at the server root."""

from routes import (
    bookings,
    claims,
    clock,
    clubs,
    contracts,
    cycles,
    facilities,
    medical,
    picks,
    prospects,
    trades,
    waivers,
)

API_PREFIX = "/draft-ops"

PREFIXED = (
    cycles.bp,
    clubs.bp,
    prospects.bp,
    waivers.bp,
    facilities.bp,
    bookings.bp,
    medical.bp,
    picks.bp,
    trades.bp,
    claims.bp,
    contracts.bp,
)

ROOT = (clock.bp,)


def register(app):
    for blueprint in PREFIXED:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    for blueprint in ROOT:
        app.register_blueprint(blueprint)
