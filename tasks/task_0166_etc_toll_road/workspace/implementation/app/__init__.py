"""Application factory for the ETC Toll Road API."""
from flask import Flask

from .errors import ApiError, register_error_handlers
from .routes.accounts import accounts_bp
from .routes.fines import fines_bp
from .routes.interop import interop_bp
from .routes.system import system_bp
from .routes.toll_events import toll_events_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    register_error_handlers(app)

    app.register_blueprint(accounts_bp)
    app.register_blueprint(toll_events_bp)
    app.register_blueprint(fines_bp)
    app.register_blueprint(interop_bp)
    app.register_blueprint(system_bp)

    return app
