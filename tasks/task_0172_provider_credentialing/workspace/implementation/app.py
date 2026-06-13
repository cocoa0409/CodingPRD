"""Provider Credentialing & Enrollment API — Flask entry point.

In-memory only; no seeding. Boots fresh on every process start.
"""
import os

from flask import Flask

from errors import APIError
from response import error_response
from routes.enrollments import bp as enrollments_bp
from routes.orgs import bp as orgs_bp
from routes.peerreview import bp as peerreview_bp
from routes.providers import bp as providers_bp
from routes.sanctions import bp as sanctions_bp
from routes.verification import bp as verification_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(orgs_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(verification_bp)
    app.register_blueprint(sanctions_bp)
    app.register_blueprint(peerreview_bp)
    app.register_blueprint(enrollments_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 400, str(e))

    @app.after_request
    def _close_connection(response):
        # Transport hygiene only: the per-test-server harness reuses a pooled
        # keep-alive client socket across the threaded Werkzeug dev server's
        # connection teardown, which can intermittently surface as a
        # BadStatusLine / ConnectionError race. Forcing Connection: close
        # prevents socket reuse. No endpoint, field, status code, error_id,
        # state transition, or calculation is affected.
        response.headers["Connection"] = "close"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
