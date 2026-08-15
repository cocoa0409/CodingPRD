"""Blueprint registration."""
from . import customers, units, quotes, rentals, service_calls, technicians, operators, leases, reconditioning, clock_route

BLUEPRINTS = [
    customers.bp,
    units.bp,
    quotes.bp,
    rentals.bp,
    service_calls.bp,
    technicians.bp,
    operators.bp,
    leases.bp,
    reconditioning.bp,
    clock_route.bp,
]
