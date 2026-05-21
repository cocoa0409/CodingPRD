"""App factory for the National Park Reservation API."""
from __future__ import annotations

from flask import Flask

from .envelope import register_request_lifecycle
from .errors import register_error_handlers
from .routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_request_lifecycle(app)
    register_error_handlers(app)
    register_routes(app)
    return app
