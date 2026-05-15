"""Application factory for the Pet Food Subscription API."""
from flask import Flask

from app.errors import register_error_handlers
from app.routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)
    register_routes(app)
    return app
