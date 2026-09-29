"""Digital Estate Fiduciary Access API -- application entry point.

All state lives in process memory (see db.py); nothing is seeded at startup and
nothing is written to disk, so every fresh boot begins with empty collections.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes.assets import bp as assets_bp
from routes.dispositions import bp as dispositions_bp
from routes.estates import bp as estates_bp
from routes.paperwork import bp as paperwork_bp
from routes.platforms import bp as platforms_bp
from routes.refunds import bp as refunds_bp
from routes.requests import bp as requests_bp
from routes.system import bp as system_bp
from routes.valuations import bp as valuations_bp

BLUEPRINTS = (
    system_bp,
    platforms_bp,
    estates_bp,
    paperwork_bp,
    assets_bp,
    requests_bp,
    dispositions_bp,
    refunds_bp,
    valuations_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "The request body could not be parsed.", 400)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "No such resource path.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Method not allowed for this path.", 405)

    @app.errorhandler(415)
    def handle_415(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Unsupported media type.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
