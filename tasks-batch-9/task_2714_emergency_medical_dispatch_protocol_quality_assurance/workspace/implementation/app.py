"""EMD protocol quality-assurance service (PRD.md).

State lives entirely in process memory; nothing is seeded at startup, so a
fresh boot is an empty programme register and every entity arrives through the
declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError
from routes.coaching import bp as coaching_bp
from routes.dispatchers import bp as dispatchers_bp
from routes.highrisk import bp as highrisk_bp
from routes.programs import bp as programs_bp
from routes.protocols import bp as protocols_bp
from routes.reports import bp as reports_bp
from routes.reviews import bp as reviews_bp
from routes.sampling import bp as sampling_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        programs_bp,
        protocols_bp,
        dispatchers_bp,
        sampling_bp,
        reviews_bp,
        highrisk_bp,
        coaching_bp,
        reports_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error(
            "ERR_INVALID_REQUEST", "The method is not allowed on this route.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            # A malformed JSON body reaches here from Flask's own parser.
            return error("ERR_INVALID_REQUEST", "The request body is invalid.", 400)
        return error(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
