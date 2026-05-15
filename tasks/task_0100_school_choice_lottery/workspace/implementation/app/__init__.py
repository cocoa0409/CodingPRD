"""Flask app factory for the School Choice Lottery API."""
from flask import Flask

from .errors import APIError, register_error_handlers
from .routes import register_blueprints
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    reset_store()
    register_error_handlers(app)
    register_blueprints(app)
    return app
