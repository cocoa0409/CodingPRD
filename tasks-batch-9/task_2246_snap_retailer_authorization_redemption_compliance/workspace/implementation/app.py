"""SNAP Retailer Authorization, Redemption and Compliance API.

Boots with an empty in-memory store on every process start: no seeding, no
persistence, no disk state of any kind.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
from routes import (applications, cases, equipment, inspectors,
                    investigations, owners, periods, pos, stores, visits)

BLUEPRINTS = (
    owners.bp,
    stores.bp,
    applications.bp,
    inspectors.bp,
    visits.bp,
    pos.bp,
    periods.bp,
    investigations.bp,
    cases.bp,
    equipment.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if isinstance(exc, ApiError):  # pragma: no cover - defensive
            return error_response(exc.error_id, exc.message, exc.http_status)
        status = exc.code or 400
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INVALID_REQUEST"
        return error_response(error_id, exc.description or "Request failed.",
                              status)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", str(exc) or "Server error.",
                              500)

    @app.get("/_health")
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False)
