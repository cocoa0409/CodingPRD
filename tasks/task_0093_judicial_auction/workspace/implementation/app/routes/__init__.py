"""Route registration."""
from flask import Flask

from . import (
    audit_routes,
    auction_routes,
    bid_routes,
    bidder_routes,
    clock_routes,
    confirmation_routes,
    deposit_routes,
    event_routes,
    lot_routes,
    payment_routes,
    sweep_routes,
    transfer_routes,
)


def register_all_routes(app: Flask) -> None:
    lot_routes.register(app)
    bidder_routes.register(app)
    auction_routes.register(app)
    bid_routes.register(app)
    deposit_routes.register(app)
    confirmation_routes.register(app)
    payment_routes.register(app)
    transfer_routes.register(app)
    audit_routes.register(app)
    clock_routes.register(app)
    sweep_routes.register(app)
    event_routes.register(app)
