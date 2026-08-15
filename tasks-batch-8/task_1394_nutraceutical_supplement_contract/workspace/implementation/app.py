"""Nutraceutical Contract Manufacturing API — Flask entry point.

In-memory only; the store starts empty on every boot. All state is built by
clients through the declared API surface.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response
from routes import batches, catalog, customers, formulas, lines, quality, recalls, orders


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    app.register_blueprint(customers.bp)
    app.register_blueprint(catalog.bp)
    app.register_blueprint(formulas.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(batches.bp)
    app.register_blueprint(quality.bp)
    app.register_blueprint(lines.bp)
    app.register_blueprint(recalls.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
