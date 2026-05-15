"""Route registration."""
from flask import Flask

from . import (
    audit_routes,
    cabinet_routes,
    clock_routes,
    compartment_routes,
    insurance_routes,
    pricing_routes,
    rental_routes,
    repair_routes,
    revenue_routes,
)


def register_all_routes(app: Flask) -> None:
    pricing_routes.register(app)
    cabinet_routes.register(app)
    compartment_routes.register(app)
    rental_routes.register(app)
    insurance_routes.register(app)
    repair_routes.register(app)
    revenue_routes.register(app)
    audit_routes.register(app)
    clock_routes.register(app)
