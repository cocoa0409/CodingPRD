"""Veterans Education Benefit Certification API — Flask entrypoint.

Storage is in-memory only and starts completely empty on every boot: nothing is
seeded, preloaded or read from disk.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:  # Flask >= 2.3 keeps key order here; older releases use the config flag.
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover
        app.config["JSON_SORT_KEYS"] = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The HTTP method is not allowed for this resource.", 405)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
