from routes import (
    clock,
    catalog,
    customers,
    lawns,
    soil_tests,
    plans,
    subscriptions,
    shipments,
    applications,
    weather,
    addons,
    invoices,
    claims,
    referrals,
    ledger,
)

MODULES = [
    clock, catalog, customers, lawns, soil_tests, plans, subscriptions,
    shipments, applications, weather, addons, invoices, claims, referrals,
    ledger,
]


def register_routes(app):
    for mod in MODULES:
        app.register_blueprint(mod.bp)
