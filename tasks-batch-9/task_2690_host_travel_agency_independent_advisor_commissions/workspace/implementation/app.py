"""Host Travel Agency Advisor Commissions API.

A single Flask process holding every row in memory.  Nothing is seeded: the
store is empty on boot and every entity is created by clients through the
declared endpoints.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
import routes_advisor
import routes_booking
import routes_claim
import routes_client
import routes_credential
import routes_reference
import routes_settlement

API_PREFIX = "/host-agency"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (routes_reference, routes_advisor, routes_credential,
                   routes_client, routes_booking, routes_claim,
                   routes_settlement):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            body = error_body("ERR_INVALID_REQUEST", "No such route.")
        elif status == 405:
            body = error_body("ERR_INVALID_REQUEST",
                              "That method is not allowed on this route.")
        else:
            body = error_body("ERR_INVALID_REQUEST",
                              exc.description or "The request could not be handled.")
            status = 400 if status < 500 else status
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
