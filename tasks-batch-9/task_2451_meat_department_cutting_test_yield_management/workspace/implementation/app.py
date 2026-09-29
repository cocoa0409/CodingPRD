"""Meat Department Cutting-Test and Yield Management API.

A fresh process starts with a completely empty in-memory store: nothing is
seeded, nothing is persisted, and nothing is read from disk.
"""

import os

from flask import Flask

import errors
from db import clear_new_flags
from errors import ApiError
from response import error_response
from routes import (case_plans, clock, cutting_tests, departments, grind_runs,
                    pre_orders, purchases, reconciliations, retail_items,
                    temperature, trim_lots)

BLUEPRINTS = (
    departments.bp,
    purchases.bp,
    retail_items.bp,
    cutting_tests.bp,
    case_plans.bp,
    trim_lots.bp,
    grind_runs.bp,
    temperature.bp,
    pre_orders.bp,
    reconciliations.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, "No such route", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_INVALID_REQUEST,
                              "The HTTP method is not allowed on this route", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST,
                              "The request could not be parsed", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return error_response(errors.ERR_INTERNAL, str(exc) or "Internal error", 500)

    @app.teardown_request
    def _teardown(_exc):
        try:
            clear_new_flags()
        except Exception:
            pass

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
