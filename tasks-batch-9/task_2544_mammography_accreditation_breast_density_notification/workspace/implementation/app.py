"""Mammography Accreditation & Breast Density Notification API.

Flask application factory and process entry point.  All state lives in process
memory (see common.Store) and starts completely empty on every boot: nothing is
seeded, preloaded or read from disk.
"""

import os
import traceback

from flask import Flask, g

from common import ApiError, error_response
import routes_core
import routes_exams
import routes_personnel
import routes_units


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_units.bp)
    app.register_blueprint(routes_personnel.bp)
    app.register_blueprint(routes_exams.bp)

    @app.before_request
    def _reset_touch_set():
        # §2.4: an entity's version advances at most once per accepted request.
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "no such route", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "method not allowed on this route", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
