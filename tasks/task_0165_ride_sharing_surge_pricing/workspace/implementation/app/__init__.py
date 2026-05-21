"""Ride-Sharing Surge Pricing API application factory."""
from flask import Flask

from .envelope import register_request_lifecycle
from .errors import register_error_handlers
from .routes import register_routes
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    reset_store()
    register_request_lifecycle(app)
    register_error_handlers(app)
    register_routes(app)

    return app
