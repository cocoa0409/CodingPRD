"""Blueprint registry. Import order is irrelevant: every path is absolute."""

from routes import (
    clock,
    credentials,
    events,
    gates,
    incidents,
    listings,
    patrons,
    reports,
    sessions,
    tickets,
    transfers,
    zones,
)

BLUEPRINTS = (
    clock.bp,
    events.bp,
    zones.bp,
    gates.bp,
    patrons.bp,
    tickets.bp,
    transfers.bp,
    listings.bp,
    credentials.bp,
    sessions.bp,
    incidents.bp,
    reports.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return app
