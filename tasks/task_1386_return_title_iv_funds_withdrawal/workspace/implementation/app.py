"""R2T4 API entry point — Flask app wiring, error handlers, route registration."""

import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response
from routes import terms, students, awards, cases, obligations, ledger


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(terms.bp)
    app.register_blueprint(students.bp)
    app.register_blueprint(awards.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(obligations.bp)
    app.register_blueprint(ledger.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response(errors.ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response(errors.ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(500)
    def handle_internal(_exc):
        return error_response(errors.ERR_INVALID_REQUEST, "internal error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
