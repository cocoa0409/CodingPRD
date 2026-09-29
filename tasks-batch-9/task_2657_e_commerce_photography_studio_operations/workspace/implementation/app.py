"""E-commerce photography studio operations API.

Single Flask process, in-memory state only, no seeded data.  Every entity is
created through the declared endpoints; all temporal behaviour reads the
server-side logical clock (POST /studio/_clock/set_current_utc).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_assets
import routes_bookings
import routes_config
import routes_retouch
import routes_samples
import routes_sessions
import routes_shotlist


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (routes_config, routes_samples, routes_sessions,
                   routes_bookings, routes_shotlist, routes_assets,
                   routes_retouch):
        app.register_blueprint(module.bp, url_prefix="/studio")

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_REFERENCE_NOT_FOUND",
                                       "No such resource path.", 404))

    @app.errorhandler(405)
    def _bad_method(_err):
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "Method not allowed for this path.", 405))

    @app.errorhandler(HTTPException)
    def _http_error(err):
        status = err.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INVALID_REQUEST"
        return error_response(ApiError(error_id, err.description, status))

    @app.errorhandler(Exception)
    def _unexpected(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
