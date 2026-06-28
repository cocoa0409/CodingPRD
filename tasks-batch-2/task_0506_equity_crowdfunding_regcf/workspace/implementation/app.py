"""Equity Crowdfunding (Reg CF) Portal API — entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.issuers import bp as issuers_bp
from routes.offerings import bp as offerings_bp
from routes.cap_table import bp as cap_table_bp
from routes.investors import bp as investors_bp
from routes.investments import bp as investments_bp
from routes.investor_updates import bp as investor_updates_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(issuers_bp)
    app.register_blueprint(offerings_bp)
    app.register_blueprint(cap_table_bp)
    app.register_blueprint(investors_bp)
    app.register_blueprint(investments_bp)
    app.register_blueprint(investor_updates_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        resp = error_response(e.error_id, e.message)
        resp.status_code = e.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(e):
        resp = error_response("ERR_NOT_FOUND", "Resource not found")
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(e):
        # Unknown method on a known path -> treat as not found per scaffold catalog.
        resp = error_response("ERR_NOT_FOUND", "Method not allowed")
        resp.status_code = 404
        return resp

    @app.errorhandler(400)
    def handle_400(e):
        resp = error_response("ERR_INVALID_REQUEST", "Malformed request")
        resp.status_code = 400
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        resp = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(e))
        resp.status_code = 400
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress, a robust production WSGI server. The Werkzeug dev
    # server can drop connections (BadStatusLine) under the concurrent
    # connection load of the per-test-server stability sweep; waitress handles
    # concurrent connections reliably. Fall back to the dev server only if
    # waitress is unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
