"""Route registration."""
from flask import Flask

from . import (
    charge_routes,
    clearance_routes,
    clock_routes,
    coding_routes,
    encounter_routes,
    patient_routes,
    payment_routes,
    policy_routes,
    write_off_routes,
)


def register_all_routes(app: Flask) -> None:
    patient_routes.register(app)
    policy_routes.register(app)
    encounter_routes.register(app)
    charge_routes.register(app)
    coding_routes.register(app)
    clearance_routes.register(app)
    payment_routes.register(app)
    write_off_routes.register(app)
    clock_routes.register(app)
