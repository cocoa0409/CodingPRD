"""Route registration."""
from flask import Flask

from . import (
    adverse_event_routes,
    appointment_routes,
    audit_routes,
    clock_routes,
    consumable_routes,
    contraindication_routes,
    customer_routes,
    followup_routes,
    installment_routes,
    plan_routes,
    project_routes,
    room_routes,
    sync_event_routes,
)


def register_all_routes(app: Flask) -> None:
    project_routes.register(app)
    contraindication_routes.register(app)
    consumable_routes.register(app)
    room_routes.register(app)
    customer_routes.register(app)
    plan_routes.register(app)
    appointment_routes.register(app)
    followup_routes.register(app)
    adverse_event_routes.register(app)
    installment_routes.register(app)
    audit_routes.register(app)
    sync_event_routes.register(app)
    clock_routes.register(app)
