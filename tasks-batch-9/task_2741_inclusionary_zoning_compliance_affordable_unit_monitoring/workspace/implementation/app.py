"""Inclusionary Zoning Compliance & Affordable Unit Monitoring API.

Flask application factory and process entry point. Storage is in-memory only
(plain dicts in db.py) and NOTHING is seeded at startup: every entity in the
system is created through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import certifications, fund, marketing, projects, reference, resale, units


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(reference.bp)
    app.register_blueprint(projects.bp)
    app.register_blueprint(units.bp)
    app.register_blueprint(marketing.bp)
    app.register_blueprint(certifications.bp)
    app.register_blueprint(resale.bp)
    app.register_blueprint(fund.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        code = exc.code or 500
        if code == 404:
            return response.error("ERR_NOT_FOUND", "Resource not found.", 404)
        if code == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        if code == 400:
            return response.error("ERR_INVALID_REQUEST",
                                  "The request payload is not well formed.", 400)
        return response.error("ERR_INTERNAL", "Internal server error.", code)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    @app.route("/health", methods=["GET"])
    def health():
        return response.ok({"status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
