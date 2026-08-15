"""Route registration."""

from routes import (
    clock,
    dqs,
    entries,
    events,
    lanes,
    meets,
    officials,
    records,
    relays,
    swimmers,
    teams,
)


def register_routes(app):
    for module in (
        meets,
        teams,
        swimmers,
        events,
        entries,
        relays,
        lanes,
        officials,
        dqs,
        records,
        clock,
    ):
        app.register_blueprint(module.bp)
