"""Route registration."""

from routes import (
    agreements,
    amendments,
    car_dwells,
    clock,
    construction_projects,
    derail_devices,
    inspections,
    liability_claims,
    segments,
    service_orders,
    storage_placements,
)


def register_routes(app):
    agreements.register(app)
    amendments.register(app)
    construction_projects.register(app)
    segments.register(app)
    inspections.register(app)
    derail_devices.register(app)
    service_orders.register(app)
    car_dwells.register(app)
    storage_placements.register(app)
    liability_claims.register(app)
    clock.register(app)
