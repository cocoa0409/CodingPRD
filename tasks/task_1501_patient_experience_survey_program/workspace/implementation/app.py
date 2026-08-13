"""Patient Experience Survey API — Flask entry point.

In-memory only; the store starts empty on every boot and nothing is seeded.
The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD 2.4) and moves
only via POST /_clock/set_current_utc.
"""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.programs import bp as programs_bp
from routes.vendors import bp as vendors_bp
from routes.units import bp as units_bp
from routes.providers import bp as providers_bp
from routes.discharges import bp as discharges_bp
from routes.cycles import bp as cycles_bp
from routes.sample_cases import bp as sample_cases_bp
from routes.responses import bp as responses_bp
from routes.initiatives import bp as initiatives_bp
from routes.tickets import bp as tickets_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        programs_bp,
        vendors_bp,
        units_bp,
        providers_bp,
        discharges_bp,
        cycles_bp,
        sample_cases_bp,
        responses_bp,
        initiatives_bp,
        tickets_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
