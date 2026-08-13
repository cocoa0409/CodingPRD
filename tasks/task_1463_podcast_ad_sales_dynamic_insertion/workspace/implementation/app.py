"""Flask entry point: error handlers, blueprint registration, server boot."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes import (
    clock,
    shows,
    episodes,
    agencies,
    advertisers,
    campaigns,
    line_items,
    ad_copies,
    ingestion,
    invoices,
    make_goods,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(shows.bp)
    app.register_blueprint(episodes.bp)
    app.register_blueprint(agencies.bp)
    app.register_blueprint(advertisers.bp)
    app.register_blueprint(campaigns.bp)
    app.register_blueprint(line_items.bp)
    app.register_blueprint(ad_copies.bp)
    app.register_blueprint(ingestion.bp)
    app.register_blueprint(invoices.bp)
    app.register_blueprint(make_goods.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Never leak a bare 500 HTML page; surface as a generic request error.
        return error_response(ERR_INVALID_REQUEST, f"Unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
