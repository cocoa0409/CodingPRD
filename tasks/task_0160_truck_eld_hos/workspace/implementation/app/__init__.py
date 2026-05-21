"""Truck ELD HOS API — Flask application factory."""

from flask import Flask

from .errors import register_error_handlers
from .routes.carriers import carriers_bp
from .routes.clock import clock_bp
from .routes.drivers import drivers_bp
from .routes.duty_events import duty_events_bp
from .routes.daily_logs import daily_logs_bp
from .routes.adverse_conditions import adverse_conditions_bp
from .routes.eld_devices import eld_devices_bp
from .routes.hos_snapshot import hos_snapshot_bp
from .routes.vehicles import vehicles_bp
from .routes.violations import violations_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False

    register_error_handlers(app)

    app.register_blueprint(carriers_bp)
    app.register_blueprint(eld_devices_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(duty_events_bp)
    app.register_blueprint(daily_logs_bp)
    app.register_blueprint(adverse_conditions_bp)
    app.register_blueprint(hos_snapshot_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(clock_bp)

    return app
