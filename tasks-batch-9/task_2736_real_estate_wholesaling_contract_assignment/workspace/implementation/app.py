"""Real-estate wholesaling contract-assignment API.

In-memory only: every collection starts empty on each boot and nothing is
seeded. State lives in `common.db` and dies with the process.
"""
import os

from flask import jsonify
from werkzeug.exceptions import HTTPException

import routes_a
import routes_b
import routes_c
import routes_d
from common import ApiError, _meta
from flask import Flask


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    routes_a.register(app)
    routes_b.register(app)
    routes_c.register(app)
    routes_d.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_body("ERR_NOT_FOUND", "No such resource or route.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_body(
            "ERR_METHOD_NOT_ALLOWED", "That method is not allowed here.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        if exc.code == 400:
            return error_body(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400
            )
        return error_body(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
