"""Corporate Meal Stipend & Group Ordering API — Flask entry point.

State lives in process memory only (see store.py); nothing is seeded at boot and
nothing is written to disk, so every fresh process starts completely empty.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask                                            # noqa: E402
from werkzeug.exceptions import HTTPException                      # noqa: E402

from envelope import error_response                                # noqa: E402
from errors import ApiError                                        # noqa: E402
from routes.claims import bp as claims_bp                          # noqa: E402
from routes.groups import bp as groups_bp                          # noqa: E402
from routes.orders import bp as orders_bp                          # noqa: E402
from routes.people import bp as people_bp                          # noqa: E402
from routes.periods import bp as periods_bp                        # noqa: E402
from routes.programs import bp as programs_bp                      # noqa: E402
from routes.rules import bp as rules_bp                            # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (programs_bp, rules_bp, people_bp, periods_bp,
                      orders_bp, groups_bp, claims_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this resource.", 405)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed as JSON.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):                        # pragma: no cover - safety net
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    @app.get("/health")
    def _health():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
