"""Flask application entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory (db.py module dicts) —
each boot starts with a completely empty store and the default logical clock
2026-05-01T00:00:00Z. No seeding, no disk persistence.
"""

import os
from flask import Flask

from errors import ApiError
from response import error_response
from util import now_iso  # noqa: F401  (kept for symmetry; timestamps via util)

from routes.clock import bp as clock_bp
from routes.seasons import bp as seasons_bp
from routes.sugarbushes import bp as sugarbushes_bp
from routes.leases import bp as leases_bp
from routes.tap_lines import bp as tap_lines_bp
from routes.weather_windows import bp as weather_windows_bp
from routes.crew import bp as crew_bp
from routes.sap_runs import bp as sap_runs_bp
from routes.batches import bp as batches_bp
from routes.syrup_lots import bp as syrup_lots_bp
from routes.packaging import bp as packaging_bp
from routes.cert_audits import bp as cert_audits_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (clock_bp, seasons_bp, sugarbushes_bp, leases_bp, tap_lines_bp,
               weather_windows_bp, crew_bp, sap_runs_bp, batches_bp,
               syrup_lots_bp, packaging_bp, cert_audits_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION", "malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"unexpected error: {err}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
