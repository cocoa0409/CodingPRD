"""Flask app factory for the Clinical Trial Matching API."""
from flask import Flask

from .errors import register_error_handlers
from .routes import register_blueprints
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve insertion order in JSON output for stable, readable responses.
    try:
        app.json.sort_keys = False  # type: ignore[attr-defined]
    except AttributeError:
        app.config["JSON_SORT_KEYS"] = False
    reset_store()
    register_error_handlers(app)
    register_blueprints(app)
    return app
