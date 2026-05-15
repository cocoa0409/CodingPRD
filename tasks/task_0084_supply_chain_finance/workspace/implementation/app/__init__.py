"""Flask application factory for the Supply Chain Finance API."""
from flask import Flask

from .errors import register_error_handlers
from .routes import register_all_routes


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    register_error_handlers(app)
    register_all_routes(app)
    return app
