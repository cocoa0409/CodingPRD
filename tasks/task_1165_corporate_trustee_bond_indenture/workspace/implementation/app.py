"""Corporate Trustee & Bond Indenture Administration API.

Flask entry point: error handlers, blueprint registration, server boot.
Storage is in-memory only (store.py); the logical clock starts at
2026-05-01T00:00:00Z (PRD 2.5). Nothing is seeded at startup.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from envelope import error_response
import errors as errmod


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_covenants
    import routes_payments
    import routes_defaults
    import routes_consents
    import routes_collateral
    import routes_fees
    import routes_trustee

    for mod in (routes_core, routes_covenants, routes_payments, routes_defaults,
                routes_consents, routes_collateral, routes_fees, routes_trustee):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND[0], 404,
                                       "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_INVALID_REQUEST[0], 400,
                                       "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unexpected error")
        return error_response(ApiError(ERR_INVALID_REQUEST[0], 400,
                                       "Unexpected request error"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
