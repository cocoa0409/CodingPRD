"""Route registration."""

from . import (bids, divisions, finance, hotels, matches, officials, ops,
               venues, volunteers, weather)


def register_routes(app):
    for module in (ops, bids, venues, hotels, divisions, matches, officials,
                   volunteers, weather, finance):
        app.register_blueprint(module.bp)
