"""Route registration."""
from flask import Flask

from . import (
    audit_routes,
    capa_routes,
    clock_routes,
    deviation_routes,
    lot_routes,
    master_data_routes,
    receipt_routes,
    recall_routes,
    shipment_routes,
    sync_event_routes,
    temperature_routes,
    warehouse_routes,
)


def register_all_routes(app: Flask) -> None:
    warehouse_routes.register(app)
    master_data_routes.register(app)
    receipt_routes.register(app)
    lot_routes.register(app)
    shipment_routes.register(app)
    temperature_routes.register(app)
    deviation_routes.register(app)
    capa_routes.register(app)
    recall_routes.register(app)
    audit_routes.register(app)
    sync_event_routes.register(app)
    clock_routes.register(app)
