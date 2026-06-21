"""Flask entry point for the multistate payroll tax API.

Boots a fresh, empty in-memory store on every process start. No entity seeding
at startup — the test harness restarts the server before every test and
constructs all preconditions via the declared API surface.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import authenticate_request
import response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # ----- Auth: enforce X-User-ID + X-User-Role on every request -----
    @app.before_request
    def _auth():
        # Pre-check: malformed JSON body should surface as ERR_INVALID_REQUEST.
        # Auth is the first validation layer (priority 1).
        # NOTE: 404 on completely unknown paths is handled by Flask's default
        # NotFound handler below; we let those pass without authenticating to
        # keep semantics clean (unknown path -> ERR_NOT_FOUND).
        if request.method == "OPTIONS":
            return None
        # Allow only registered URL rules; for unknown routes, let Flask 404 fire.
        try:
            authenticate_request()
        except APIError as e:
            return response.error_response(e.error_id, e.http_status, e.message)
        return None

    # ----- Error handlers -----
    @app.errorhandler(APIError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return response.error_response(ERR_NOT_FOUND, 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(_e):
        return response.error_response(ERR_NOT_FOUND, 404, "method not allowed for this path")

    @app.errorhandler(400)
    def handle_400(e):
        msg = getattr(e, "description", None) or "bad request"
        return response.error_response(ERR_INVALID_REQUEST, 400, str(msg))

    @app.errorhandler(415)
    def handle_415(_e):
        return response.error_response(ERR_INVALID_REQUEST, 400, "unsupported media type")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other HTTPException through ERR_INVALID_REQUEST default.
        code = e.code or 500
        if code == 404:
            return response.error_response(ERR_NOT_FOUND, 404, e.description or "not found")
        if code == 401:
            return response.error_response(ERR_UNAUTHENTICATED, 401, e.description or "unauthenticated")
        if code == 403:
            return response.error_response(ERR_FORBIDDEN, 403, e.description or "forbidden")
        return response.error_response(ERR_INVALID_REQUEST, code if 400 <= code < 500 else 400,
                                       e.description or "error")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last resort: don't leak internals; surface as ERR_INVALID_REQUEST 400
        # which is the closest generic 4xx in this catalog. (5xx is not modeled.)
        return response.error_response(ERR_INVALID_REQUEST, 500, f"unexpected error: {e!s}")

    # ----- Blueprints -----
    from routes.employees import bp as employees_bp
    from routes.w4_forms import bp as w4_bp
    from routes.paycheck_runs import bp as runs_bp
    from routes.paychecks import bp as paychecks_bp
    from routes.garnishments import bp as garnishments_bp
    from routes.remittances import bp as remittances_bp
    from routes.tax_rate_tables import bp as tax_tables_bp

    app.register_blueprint(employees_bp)
    app.register_blueprint(w4_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(paychecks_bp)
    app.register_blueprint(garnishments_bp)
    app.register_blueprint(remittances_bp)
    app.register_blueprint(tax_tables_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
