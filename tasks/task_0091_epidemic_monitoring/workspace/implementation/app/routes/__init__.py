"""Route registration."""
from flask import Flask

from . import (
    audit_routes,
    bulletin_routes,
    case_routes,
    clock_routes,
    contact_routes,
    event_routes,
    facility_routes,
    institution_routes,
    isolation_routes,
    person_routes,
    region_routes,
    risk_routes,
    supply_routes,
    sweep_routes,
    test_reset_routes,
    test_routes,
    tracing_routes,
)


def register_all_routes(app: Flask) -> None:
    institution_routes.register(app)
    region_routes.register(app)
    person_routes.register(app)
    facility_routes.register(app)
    case_routes.register(app)
    contact_routes.register(app)
    tracing_routes.register(app)
    isolation_routes.register(app)
    test_routes.register(app)
    risk_routes.register(app)
    supply_routes.register(app)
    bulletin_routes.register(app)
    audit_routes.register(app)
    clock_routes.register(app)
    sweep_routes.register(app)
    event_routes.register(app)
    test_reset_routes.register(app)
