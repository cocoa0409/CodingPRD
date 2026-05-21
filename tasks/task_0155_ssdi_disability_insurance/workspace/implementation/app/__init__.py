"""Flask application factory for the SSDI Disability Insurance API."""

from flask import Flask

from app.envelope import register_error_handlers
from app.routes import register_blueprints


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_blueprints(app)
    register_error_handlers(app)
    return app
