"""VA Benefits API package."""
from flask import Flask

from .errors import register_error_handlers
from .routes import register_blueprints
from .store import Store


def create_app() -> Flask:
    app = Flask(__name__)
    # Strict path matching, etc.
    app.url_map.strict_slashes = False

    # Single in-memory data store shared by every request.
    app.config["STORE"] = Store()

    register_error_handlers(app)
    register_blueprints(app)
    return app
