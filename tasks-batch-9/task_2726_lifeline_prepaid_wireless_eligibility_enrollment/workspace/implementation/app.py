"""Lifeline Prepaid Wireless Eligibility & Enrollment API.

In-memory only: the store starts empty on every boot and nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (addresses, cases, claims, clock, devices, eligibility,
                    enrollments, providers, subscribers, transfers)

BLUEPRINTS = (
    providers.bp,
    addresses.bp,
    subscribers.bp,
    eligibility.bp,
    enrollments.bp,
    devices.bp,
    transfers.bp,
    claims.bp,
    cases.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        code = exc.code or 500
        if code == 404:
            return response.error_body("ERR_NOT_FOUND",
                                       "The requested resource does not exist", 404)
        if code == 405:
            return response.error_body("ERR_INVALID_REQUEST",
                                       "Method not allowed on this path", 405)
        if code in (400, 415):
            return response.error_body("ERR_INVALID_REQUEST",
                                       "The request could not be parsed", 422)
        return response.error_body("ERR_INTERNAL", exc.description or "Error", code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        import traceback
        traceback.print_exc()
        return response.error_body("ERR_INTERNAL", str(exc) or "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
