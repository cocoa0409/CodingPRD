"""Flask application factory: blueprint registration and error rendering."""

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_accounts
    import routes_billing
    import routes_config
    import routes_loaners
    import routes_lockers
    import routes_requests
    import routes_route
    import routes_subscriptions
    import routes_warranty

    for module in (
        routes_config,
        routes_accounts,
        routes_subscriptions,
        routes_route,
        routes_requests,
        routes_lockers,
        routes_loaners,
        routes_warranty,
        routes_billing,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return envelope.error(
                "ERR_VALIDATION", "No such resource path.", 404
            )
        if status == 405:
            return envelope.error(
                "ERR_VALIDATION", "Method not allowed on this path.", 405
            )
        return envelope.error("ERR_VALIDATION", exc.description or "Bad request", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return envelope.error("ERR_VALIDATION", str(exc), 400)

    return app
