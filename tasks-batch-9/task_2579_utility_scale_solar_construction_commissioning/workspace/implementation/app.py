"""Utility-Scale Solar Construction & Commissioning API.

Flask application factory and wiring. All state lives in process memory
(see store.py) and disappears when the process exits; nothing is seeded.
"""

import os

from flask import Blueprint, Flask
from werkzeug.exceptions import HTTPException

import clock
import envelope
from errors import ApiError
from validate import ALL_ROLES, authorize, body, dt

from routes import arrays, civil, commissioning, grid, payroll, projects, punch, yard

clock_bp = Blueprint("clock_control", __name__)


@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    """Test-driving hook for the single logical UTC clock (PRD 2.5)."""
    authorize(*ALL_ROLES)
    data = body(dt("now"))
    clock.set_now(data["now"])
    return envelope.ok({"now": clock.fmt_datetime(clock.now())})


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(projects.bp)
    app.register_blueprint(civil.bp)
    app.register_blueprint(yard.bp)
    app.register_blueprint(arrays.bp)
    app.register_blueprint(grid.bp)
    app.register_blueprint(commissioning.bp)
    app.register_blueprint(punch.bp)
    app.register_blueprint(payroll.bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return envelope.error(
            "ERR_INVALID_REQUEST", exc.description or exc.name, exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return envelope.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
