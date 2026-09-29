"""Multi-Dose Adherence Packaging & Mail-Order Fulfillment API.

Boots with completely empty in-memory storage: no seeding, no preloading, no
fixture data.  Every dict in ``db`` is fresh on each process start, which is
what the ``--isolation per-test-server`` harness expects.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
import response
from errors import ApiError
from routes import (
    auths,
    cycles,
    patients,
    prescriptions,
    reads,
    rolls,
    setup,
    shipments,
    vacations,
)

API_PREFIX = "/pharmacy"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (
        setup,
        reads,
        patients,
        cycles,
        rolls,
        shipments,
        auths,
        vacations,
        prescriptions,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _not_found(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "No such route on this API.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request body is malformed.", 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", error.description or "Request failed.", error.code
        )

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - safety net
        return response.error_response("ERR_INVALID_REQUEST", str(error), 500)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "current_utc": clock.now_iso()}), 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
