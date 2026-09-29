"""GFCO gluten-free certification and facility audit API.

Storage is entirely in-memory (see db.py); nothing is seeded at import time, so
each start.sh invocation begins from a completely empty program with the
logical clock parked at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    applicants,
    audits,
    certificates,
    change_notifications,
    consumer_complaints,
    facilities,
    ingredients,
    lot_tests,
    nonconformances,
    product_ingredients,
    products,
    supplier_documents,
    suppliers,
    system,
)

BLUEPRINTS = (
    applicants.bp,
    suppliers.bp,
    facilities.bp,
    supplier_documents.bp,
    ingredients.bp,
    products.bp,
    product_ingredients.bp,
    lot_tests.bp,
    audits.bp,
    certificates.bp,
    nonconformances.bp,
    change_notifications.bp,
    consumer_complaints.bp,
    system.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED",
                "The method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return response.error(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return response.error(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
