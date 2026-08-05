"""Mobile Dentistry API entry point.

Storage is in-memory only and starts completely empty on every boot: no row is
seeded, preloaded, registered or hardcoded at startup.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (
    coverage,
    encounters,
    equipment,
    periods,
    plans,
    procedures,
    reports,
    roster,
    sites,
    visits,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        pass

    app.register_blueprint(periods.bp)
    app.register_blueprint(sites.bp)
    app.register_blueprint(roster.bp)
    app.register_blueprint(equipment.bp)
    app.register_blueprint(visits.bp)
    app.register_blueprint(encounters.bp)
    app.register_blueprint(procedures.bp)
    app.register_blueprint(plans.bp)
    app.register_blueprint(coverage.bp)
    app.register_blueprint(reports.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            code = exc.code or 500
            if code in (404, 405):
                return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
            if 400 <= code < 500:
                return error_response("ERR_VALIDATION", exc.description or "Bad request.", code)
            return error_response("ERR_INTERNAL", exc.description or "Internal error.", code)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
