"""Hospital Cost Accounting API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding).
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask

from db import store
from errors import ApiError, err
from response import error_response
from routes_budget import bp as budget_bp
from routes_cases import bp as cases_bp
from routes_models import bp as models_bp
from routes_reference import bp as reference_bp
from routes_reports import bp as reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(reports_bp)

    @app.before_request
    def _serialize_requests():
        # The store is plain dicts; a process-wide lock makes every request
        # atomic (read-modify-write cascades included).
        store.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        store.lock.release()

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err("ERR_INVALID_REQUEST", 400,
                                  "Malformed request: %s" % e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
