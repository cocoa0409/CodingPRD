"""Paratransit Eligibility Assessment API — entry point.

Storage is in-memory only and starts empty on every boot: no entity is seeded,
preloaded or hardcoded here or anywhere else.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

from routes.reads import bp as reads_bp
from routes.intake import bp as intake_bp
from routes.scheduling import bp as scheduling_bp
from routes.determinations import bp as determinations_bp
from routes.appeals import bp as appeals_bp
from routes.conduct_routes import bp as conduct_bp
from routes.training import bp as training_bp
from routes.visitors import bp as visitors_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        reads_bp,
        intake_bp,
        scheduling_bp,
        determinations_bp,
        appeals_bp,
        conduct_bp,
        training_bp,
        visitors_bp,
        ops_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 400)
        if exc.code and 400 <= exc.code < 500:
            return error_response("ERR_INVALID_REQUEST", str(exc.description), 400)
        return error_response("ERR_INVALID_REQUEST", str(exc.description), 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
