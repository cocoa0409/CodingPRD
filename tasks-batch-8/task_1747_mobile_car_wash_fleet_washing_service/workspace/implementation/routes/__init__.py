"""Blueprint registration."""

from routes import (
    clock_ops, customers, sites, vehicles, contracts, subscriptions, orders,
    routes_stops, vans, technicians, reports, claims, audits, incidents,
    invoices,
)

ALL_BLUEPRINTS = [
    clock_ops.bp,
    customers.bp,
    sites.bp,
    vehicles.bp,
    contracts.bp,
    subscriptions.bp,
    orders.bp,
    routes_stops.bp,
    vans.bp,
    technicians.bp,
    reports.bp,
    claims.bp,
    audits.bp,
    incidents.bp,
    invoices.bp,
]
