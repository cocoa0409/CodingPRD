"""HSA/FSA Health Accounts API — Flask application factory."""
from flask import Flask

from .errors import ApiError, register_error_handlers
from .responses import register_request_hooks
from .routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve key ordering in JSON responses for deterministic output.
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    register_request_hooks(app)
    register_error_handlers(app)
    register_routes(app)

    return app
