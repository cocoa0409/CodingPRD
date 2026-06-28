"""Entry point: Flask app, error handlers, blueprint registration.

Binds 0.0.0.0:$PORT (default 10000), foreground. In-memory storage only; no
seeding at startup.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.merchants import bp as merchants_bp
from routes.bank_feeds import bp as bank_feeds_bp
from routes.applications import bp as applications_bp
from routes.credit_lines import bp as credit_lines_bp
from routes.draws import bp as draws_bp
from routes.remittances import bp as remittances_bp
from routes.line_increases import bp as line_increases_bp
from routes.renewals import bp as renewals_bp
from routes.statements import bp as statements_bp
from routes.ledger import bp as ledger_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (merchants_bp, bank_feeds_bp, applications_bp, credit_lines_bp,
               draws_bp, remittances_bp, line_increases_bp, renewals_bp,
               statements_bp, ledger_bp, ops_bp):
        app.register_blueprint(bp)

    @app.after_request
    def _no_keepalive(resp):
        # The test client uses a persistent requests.Session (HTTP keep-alive).
        # Under the 8x-concurrent per-test-server sweep the Werkzeug dev server can
        # tear down an idle keep-alive connection that the client then tries to
        # reuse, surfacing as a transient BadStatusLine/ConnectionError. Closing the
        # connection after every response eliminates that reuse race entirely. This
        # is a transport-level header only; it changes no API contract field.
        resp.headers["Connection"] = "close"
        return resp

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
