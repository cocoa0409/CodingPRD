"""Blueprint registration."""


def register_routes(app):
    from . import (audit, catalog, distribution, holds, offers, ops, payments,
                   racks, service, subscriptions)
    for mod in (catalog, subscriptions, holds, offers, service, payments,
                distribution, racks, audit, ops):
        app.register_blueprint(mod.bp)
