"""Marriage License & Vital Records API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.applicants import bp as applicants_bp
from routes.officiants import bp as officiants_bp
from routes.applications import bp as applications_bp
from routes.licenses import bp as licenses_bp
from routes.returns import bp as returns_bp
from routes.records import bp as records_bp
from routes.certified_copies import bp as certified_copies_bp
from routes.amendments import bp as amendments_bp
from routes.apostilles import bp as apostilles_bp
from routes.fee_waivers import bp as fee_waivers_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(applicants_bp)
    app.register_blueprint(officiants_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(records_bp)
    app.register_blueprint(certified_copies_bp)
    app.register_blueprint(amendments_bp)
    app.register_blueprint(apostilles_bp)
    app.register_blueprint(fee_waivers_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        # Malformed JSON and similar client errors surface as ERR_INVALID_REQUEST.
        code = err.code or 500
        if 400 <= code < 500:
            return error_response("ERR_INVALID_REQUEST", err.description or "Bad request", 400)
        return error_response("ERR_INTERNAL", err.description or "Internal error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer a production-grade WSGI server (waitress) with a generous connection
    # backlog: under the benchmark's 8-round concurrent sweep the host CPU is
    # saturated, and the Werkzeug dev server occasionally drops a connection
    # mid-request (surfacing client-side as BadStatusLine). Waitress queues
    # connections properly and survives the burst. Fall back to the threaded dev
    # server if waitress is unavailable on the host.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, backlog=256,
              connection_limit=512, channel_timeout=120)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
