"""Application factory for the Timekeeping & FLSA Overtime API."""
from flask import Flask

from .errors import register_error_handlers
from .routes.employees import bp_employees
from .routes.shifts import bp_shifts
from .routes.time_edits import bp_time_edits
from .routes.workweeks import bp_workweeks
from .routes.audit import bp_audit
from .routes.system import bp_system


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(bp_employees)
    app.register_blueprint(bp_shifts)
    app.register_blueprint(bp_time_edits)
    app.register_blueprint(bp_workweeks)
    app.register_blueprint(bp_audit)
    app.register_blueprint(bp_system)

    register_error_handlers(app)
    return app
