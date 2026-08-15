"""Blueprint registry."""
from routes import facilities, units, stocks, par_levels, cart_runs, manifests, \
    invoices, complaints, surges, clock_routes

BLUEPRINTS = [
    facilities.bp,
    units.bp,
    stocks.bp,
    par_levels.bp,
    cart_runs.bp,
    manifests.bp,
    invoices.bp,
    complaints.bp,
    surges.bp,
    clock_routes.bp,
]
