"""Server package — Flask app factory and route registration."""
from flask import Flask

from .errors import ApiError, register_error_handlers
from .responses import json_error
from .routes import register_all_routes


def create_app() -> Flask:
    app = Flask(__name__)
    # Disable Flask's automatic 404 / 405 HTML pages so we emit our envelope.
    app.url_map.strict_slashes = False

    register_error_handlers(app)
    register_all_routes(app)

    return app


__all__ = ["create_app", "ApiError", "json_error"]
