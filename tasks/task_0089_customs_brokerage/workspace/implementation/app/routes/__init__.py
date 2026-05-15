"""Route registration."""
from flask import Flask

from . import (
    agreement_routes,
    audit_routes,
    client_routes,
    clock_routes,
    declaration_routes,
    document_routes,
    event_routes,
    inspection_routes,
    rejection_routes,
    settlement_routes,
)


def register_all_routes(app: Flask) -> None:
    client_routes.register(app)
    agreement_routes.register(app)
    declaration_routes.register(app)
    document_routes.register(app)
    inspection_routes.register(app)
    settlement_routes.register(app)
    audit_routes.register(app)
    rejection_routes.register(app)
    event_routes.register(app)
    clock_routes.register(app)
