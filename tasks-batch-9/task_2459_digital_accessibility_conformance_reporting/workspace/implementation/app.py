"""Digital Accessibility Conformance API — Flask application factory.

Storage is in-memory only and starts completely empty on every boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ERROR_STATUS, ApiError
from response import error_response
from routes.assessments import bp as assessments_bp
from routes.clock import bp as clock_bp
from routes.complaints import bp as complaints_bp
from routes.issues import bp as issues_bp
from routes.products import bp as products_bp
from routes.questionnaires import bp as questionnaires_bp
from routes.reports import bp as reports_bp
from routes.runs import bp as runs_bp
from routes.standards import bp as standards_bp
from routes.trains import bp as trains_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (standards_bp, products_bp, runs_bp, assessments_bp, reports_bp,
                      trains_bp, issues_bp, questionnaires_bp, complaints_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this path", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "Request body is invalid: malformed request", 400)
        return error_response("ERR_INTERNAL", exc.description or "Internal error",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error",
                              ERROR_STATUS["ERR_INTERNAL"])

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
