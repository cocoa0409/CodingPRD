"""Flask entry point for the Theatrical Rights Licensing API."""
import os

from flask import Flask, jsonify

import db
from errors import ApiError
from response import error_response, _meta

from routes.titles import bp as titles_bp
from routes.organizations import bp as organizations_bp
from routes.applications import bp as applications_bp
from routes.agreements import bp as agreements_bp
from routes.performances import bp as performances_bp
from routes.rentals import bp as rentals_bp
from routes.alteration_requests import bp as alteration_requests_bp
from routes.recording_grants import bp as recording_grants_bp
from routes.fines import bp as fines_bp
from routes.availability import bp as availability_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        titles_bp,
        organizations_bp,
        applications_bp,
        agreements_bp,
        performances_bp,
        rentals_bp,
        alteration_requests_bp,
        recording_grants_bp,
        fines_bp,
        availability_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        e = ApiError("ERR_NOT_FOUND", "Resource not found", 404)
        return error_response(e)

    @app.errorhandler(405)
    def handle_405(err):
        e = ApiError("ERR_NOT_FOUND", "Method not allowed", 404)
        return error_response(e)

    @app.errorhandler(400)
    def handle_400(err):
        e = ApiError("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error_response(e)

    @app.errorhandler(Exception)
    def handle_generic(err):
        if isinstance(err, ApiError):
            return error_response(err)
        e = ApiError("ERR_INVALID_REQUEST", f"Unhandled error: {err}", 400)
        return error_response(e)

    return app


app = create_app()

if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # The per-test-server harness kill -9's the previous server on this port and
    # immediately spawns a new one; if the old process has not fully released
    # the listen socket yet, the first bind attempt can fail with EADDRINUSE.
    # Retry the bind for up to ~10s so the boot survives that race (the
    # harness's readiness poll window is 15s).
    for _attempt in range(20):
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit("could not bind port after retries")
