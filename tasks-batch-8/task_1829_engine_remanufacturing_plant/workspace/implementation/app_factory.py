"""Flask application factory: blueprint registration and error rendering."""

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_distributors
    import routes_engines
    import routes_ops
    import routes_specs
    import routes_warranty
    import routes_work

    for module in (
        routes_distributors,
        routes_core,
        routes_specs,
        routes_work,
        routes_engines,
        routes_warranty,
        routes_ops,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return envelope.error("ERR_NOT_FOUND", "No such resource path.", 404)
        if status == 405:
            return envelope.error(
                "ERR_VALIDATION", "Method not allowed on this path.", 405
            )
        return envelope.error("ERR_VALIDATION", exc.description or "Bad request", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        import traceback

        traceback.print_exc()
        return envelope.error("ERR_VALIDATION", str(exc), 400)

    return app
