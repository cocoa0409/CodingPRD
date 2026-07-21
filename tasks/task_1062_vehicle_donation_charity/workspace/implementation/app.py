"""Vehicle-Donation Charity API — entry point and error handling."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as resp
from errors import ApiError
from routes import (
    batches,
    donations,
    lots,
    ops,
    pickups,
    receipts,
    reference,
    titles,
    vehicles,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference.bp)
    app.register_blueprint(donations.bp)
    app.register_blueprint(vehicles.bp)
    app.register_blueprint(titles.bp)
    app.register_blueprint(pickups.bp)
    app.register_blueprint(lots.bp)
    app.register_blueprint(receipts.bp)
    app.register_blueprint(batches.bp)
    app.register_blueprint(ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return resp.error("ERR_DONATION_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return resp.error("ERR_UNAUTHORIZED", "Method not allowed.", 403)
        if exc.code == 400:
            return resp.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return resp.error("ERR_INVALID_REQUEST", str(exc), exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return resp.error("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
