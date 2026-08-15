"""Route blueprints."""
from routes import (
    billing, clock, crews, districts, exceptions, poles, programs, reports,
    routes_ops, salvage, tickets, work_orders,
)

ALL_BLUEPRINTS = [
    programs.bp,
    districts.bp,
    poles.bp,
    crews.bp,
    routes_ops.bp,
    work_orders.bp,
    billing.bp,
    tickets.bp,
    salvage.bp,
    reports.bp,
    exceptions.bp,
    clock.bp,
]
