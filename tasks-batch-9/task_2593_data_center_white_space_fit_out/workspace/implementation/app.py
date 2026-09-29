"""Data Center White Space Fit-Out API.

Storage is a set of in-memory dicts that start EMPTY on every boot: nothing is
seeded, preloaded or read from disk.  The process is relaunched before every
test, so a fresh boot must always present a fresh, empty system.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.commissioning import bp as commissioning_bp
from routes.electrical import bp as electrical_bp
from routes.halls import bp as halls_bp
from routes.mechanical import bp as mechanical_bp
from routes.mops import bp as mops_bp
from routes.racks import bp as racks_bp
from routes.release_packets import bp as release_packets_bp
from routes.security import bp as security_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in (
        halls_bp,
        electrical_bp,
        mechanical_bp,
        security_bp,
        racks_bp,
        commissioning_bp,
        mops_bp,
        release_packets_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_NOT_FOUND", "That method is not allowed on this path.", 405
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_VALIDATION", "The request body could not be read.", 422
            )
        return error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
