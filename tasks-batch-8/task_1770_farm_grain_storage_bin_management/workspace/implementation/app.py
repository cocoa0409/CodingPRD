"""Farm Grain Bin Management API — Flask entry point.

In-memory only; the store starts empty on every boot (per-test-server
isolation: the harness re-launches start.sh before every test).
"""
import os

from flask import Flask

from errors import ApiError
from response import err


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    from routes import (applicators, alerts, assessments, bins, clock,
                        contracts, fumigations, insurance, loadouts, lots,
                        permits, readings)
    for mod in (applicators, alerts, assessments, bins, clock, contracts,
                fumigations, insurance, loadouts, lots, permits, readings):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.http_status, e.message)
        import traceback
        traceback.print_exc()
        return err("ERR_VALIDATION", 400, f"unexpected error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
