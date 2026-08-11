"""Blueprint registration."""


def register_blueprints(app):
    from . import (
        appointments_bp,
        barns,
        clients,
        clock_bp,
        farriers,
        horses,
        inventory_routes,
        invoices_bp,
        lameness_bp,
        ratecards,
        reminders_bp,
        routes_bp,
        servicelines,
        stops,
    )

    for module in (
        barns,
        clients,
        horses,
        farriers,
        inventory_routes,
        ratecards,
        routes_bp,
        stops,
        appointments_bp,
        servicelines,
        lameness_bp,
        invoices_bp,
        reminders_bp,
        clock_bp,
    ):
        app.register_blueprint(module.bp)
