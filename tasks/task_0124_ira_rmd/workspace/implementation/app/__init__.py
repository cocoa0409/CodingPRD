"""Flask application factory for the IRA Management & RMD Calculation API."""
from flask import Flask

from .errors import register_error_handlers
from .routes import register_blueprints
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    try:
        app.json.sort_keys = False  # type: ignore[attr-defined]
    except AttributeError:
        app.config["JSON_SORT_KEYS"] = False
    reset_store()
    register_error_handlers(app)
    register_blueprints(app)
    return app
