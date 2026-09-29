"""Concert promoter show settlement and risk service.

Flask application factory and global error handling.  All state lives in
process memory (see store.py); nothing is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes.budget import bp as budget_bp
from routes.cancellations import bp as cancellations_bp
from routes.core import bp as core_bp
from routes.offers import bp as offers_bp
from routes.settlements import bp as settlements_bp
from routes.shows import bp as shows_bp
from routes.tickets import bp as tickets_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(core_bp)
    app.register_blueprint(shows_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(cancellations_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if status == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "method not allowed for this path", 405)
        if status == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  exc.description or "malformed request", 400)
        return error_response("ERR_INTERNAL", exc.description or "error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
