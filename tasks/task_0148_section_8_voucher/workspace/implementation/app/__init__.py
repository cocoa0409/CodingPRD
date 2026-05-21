"""Flask application factory for the Section 8 Housing Voucher API."""

from flask import Flask

from app.envelope import register_error_handlers
from app.routes import register_blueprints


API_PREFIX = "/housing-voucher"


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_blueprints(app, API_PREFIX)
    register_error_handlers(app)
    return app
