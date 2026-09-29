"""Open Access Publishing Fee & Repository Deposit API.

A single Flask process holding all state in memory. Nothing is seeded: every
row is created through the declared endpoints, and every boot starts empty
with the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from clock import clock
from db import db
from errors import ApiError
from response import error_response
from routes.articles import bp as articles_bp
from routes.deposits import bp as deposits_bp
from routes.fund_requests import bp as fund_requests_bp
from routes.invoices import bp as invoices_bp
from routes.ops import bp as ops_bp
from routes.reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    clock.reset()
    db.reset()

    app.register_blueprint(reference_bp)
    app.register_blueprint(articles_bp)
    app.register_blueprint(fund_requests_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if error.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed here.", 405
            )
        if error.code and error.code < 500:
            return error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        app.logger.exception("unhandled error: %s", error)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
