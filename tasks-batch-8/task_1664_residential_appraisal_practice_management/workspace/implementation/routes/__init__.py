"""Route registration: every module's register(app) attaches its endpoints."""


def register_routes(app):
    from routes import (
        routes_admin,
        routes_appraisers,
        routes_appointments,
        routes_clients,
        routes_comparables,
        routes_complaints,
        routes_fees,
        routes_orders,
        routes_panels,
        routes_reports,
        routes_revisions,
        routes_workfiles,
    )

    for module in (
        routes_admin,
        routes_clients,
        routes_appraisers,
        routes_panels,
        routes_fees,
        routes_orders,
        routes_appointments,
        routes_comparables,
        routes_reports,
        routes_revisions,
        routes_workfiles,
        routes_complaints,
    ):
        module.register(app)
