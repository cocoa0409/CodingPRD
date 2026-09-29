"""County Address and Emergency Response GIS API.

All state lives in memory (see store.py) and is empty at startup: the process
encodes the system's rules, never any data.
"""

import os

from flask import Flask

from envelope import error
from errors import ApiError
from routes import boundaries, config, disc, packages, points, qc, requests, roads

API_PREFIX = "/gis"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (config, roads, points, requests, boundaries, qc, packages, disc):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error("ERR_INVALID_REQUEST", "That method is not allowed on this route.", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
