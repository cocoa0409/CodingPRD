"""Route registration."""
from flask import Flask

from . import (
    borrower_routes,
    clock_routes,
    collections_routes,
    discharge_routes,
    employment_routes,
    hardship_routes,
    health_routes,
    loan_routes,
    payment_routes,
    plan_routes,
    summary_routes,
)


def register_all_routes(app: Flask) -> None:
    health_routes.register(app)
    clock_routes.register(app)
    borrower_routes.register(app)
    loan_routes.register(app)
    payment_routes.register(app)
    plan_routes.register(app)
    hardship_routes.register(app)
    discharge_routes.register(app)
    employment_routes.register(app)
    collections_routes.register(app)
    summary_routes.register(app)
