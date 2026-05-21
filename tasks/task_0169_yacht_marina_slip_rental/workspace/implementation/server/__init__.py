"""Server package — Flask application factory for Yacht/Marina Slip Rental API."""
from flask import Flask

from .errors import register_error_handlers
from .routes import register_blueprints


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)
    register_blueprints(app)
    return app


__all__ = ["create_app"]
