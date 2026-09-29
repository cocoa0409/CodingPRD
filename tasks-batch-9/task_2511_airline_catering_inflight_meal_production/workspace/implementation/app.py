"""Airline catering / in-flight meal production service.

Storage is in-memory only and is never seeded: every boot starts with an empty
dataset and the logical clock at its default instant.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import audit, carts, delivery, flights, manifests, orders, production, reference, uplift

BLUEPRINTS = (
    reference.bp,
    flights.bp,
    orders.bp,
    production.bp,
    carts.bp,
    manifests.bp,
    delivery.bp,
    uplift.bp,
    audit.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error(
                "ERR_RESOURCE_NOT_FOUND", "The requested path does not exist.", 404
            )
        if exc.code == 405:
            return response.error(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed for this path.",
                405,
            )
        if exc.code in (400, 411, 413, 415):
            return response.error(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INTERNAL_ERROR", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
