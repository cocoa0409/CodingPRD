"""Grant Management API — entry point.

Registers all blueprints and the global error handlers, then runs the Flask
dev server bound to 0.0.0.0:$PORT (default 10000) in the foreground.

State is entirely in-memory (see db.py). NOTHING is seeded at startup; every
entity is created by a test via the declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error as error_response

from routes.applications import bp as applications_bp
from routes.awards import bp as awards_bp
from routes.indirect_cost_rates import bp as indirect_cost_rates_bp
from routes.subawards import bp as subawards_bp
from routes.restricted_funds import bp as restricted_funds_bp
from routes.drawdowns import bp as drawdowns_bp
from routes.financial_reports import bp as financial_reports_bp
from routes.progress_reports import bp as progress_reports_bp
from routes.single_audits import bp as single_audits_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(applications_bp)
    app.register_blueprint(awards_bp)
    app.register_blueprint(indirect_cost_rates_bp)
    app.register_blueprint(subawards_bp)
    app.register_blueprint(restricted_funds_bp)
    app.register_blueprint(drawdowns_bp)
    app.register_blueprint(financial_reports_bp)
    app.register_blueprint(progress_reports_bp)
    app.register_blueprint(single_audits_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Unmatched route / method -> map onto the error envelope. Declared
        # endpoints never reach here; this only covers genuinely unknown URLs.
        if exc.code == 404:
            return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)
        if exc.code == 405:
            return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 405)
        message = exc.description or exc.name or "HTTP error."
        return error_response("ERR_HTTP", message, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


def _serve(port):
    """Bind 0.0.0.0:port in the foreground with a short bind-retry loop.

    Under --isolation per-test-server the process is killed and re-launched via
    start.sh before every test. On a rapid restart the previous listener's
    socket can still be in TIME_WAIT, so a naive bind can fail with
    'address already in use'. We build the WSGI server with SO_REUSEADDR (the
    Werkzeug default) and retry the bind a few times before giving up, so a
    transient restart race never masquerades as a server that 'could not be
    restarted'.
    """
    import errno
    import time

    from werkzeug.serving import make_server

    last_exc = None
    for attempt in range(40):
        try:
            server = make_server("0.0.0.0", port, app, threaded=True)
            break
        except OSError as exc:
            last_exc = exc
            if exc.errno in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                time.sleep(0.25)
                continue
            raise
    else:
        raise last_exc
    server.serve_forever()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _serve(port)
