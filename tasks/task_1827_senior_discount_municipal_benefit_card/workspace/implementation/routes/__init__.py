from . import applications, cardholders, clock_routes, funding, merchants, usage

BLUEPRINTS = [
    clock_routes.bp,
    applications.bp,
    cardholders.bp,
    merchants.bp,
    usage.bp,
    funding.bp,
]
