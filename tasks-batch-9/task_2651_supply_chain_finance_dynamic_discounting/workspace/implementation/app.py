"""Supply-chain finance dynamic discounting API.

Entry point: registers every route group, installs the error handlers that
render the PRD 2.2 error envelope, and serves on 0.0.0.0:$PORT.
The in-memory store starts empty on every boot; nothing is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.buyers import bp as buyers_bp
from routes.clock import bp as clock_bp
from routes.files import bp as files_bp
from routes.funders import bp as funders_bp
from routes.invoices import bp as invoices_bp
from routes.offers import bp as offers_bp
from routes.payments import bp as payments_bp
from routes.programs import bp as programs_bp
from routes.sessions import bp as sessions_bp
from routes.suppliers import bp as suppliers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:  # Flask >= 2.2 moves the flag onto the json provider
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        pass

    for blueprint in (
        buyers_bp,
        programs_bp,
        sessions_bp,
        suppliers_bp,
        files_bp,
        invoices_bp,
        offers_bp,
        funders_bp,
        payments_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "The requested resource does not exist.", 404
            )
        if status == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed on this resource.", 405
            )
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
