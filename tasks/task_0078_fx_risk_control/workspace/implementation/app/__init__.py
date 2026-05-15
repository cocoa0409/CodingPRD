"""Application factory for the FX Risk Control API."""
from flask import Flask

from app.errors import ApiError, register_error_handlers
from app.routes import register_blueprints


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)
    register_blueprints(app)
    return app


__all__ = ["create_app", "ApiError"]
