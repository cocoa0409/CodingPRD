from routes import (
    carriers,
    clock,
    configs,
    credentials,
    disputes,
    events,
    inspections,
    invoices,
    overrides,
    snapshots,
    stations,
    subscriptions,
    vehicles,
)


def register_all(app):
    for mod in (
        clock,
        carriers,
        configs,
        stations,
        vehicles,
        credentials,
        snapshots,
        events,
        disputes,
        overrides,
        subscriptions,
        invoices,
        inspections,
    ):
        app.register_blueprint(mod.bp)
