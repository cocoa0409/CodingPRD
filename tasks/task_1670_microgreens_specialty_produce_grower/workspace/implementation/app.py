"""Microgreens & Specialty Produce Grower API — Flask entry point."""
import os

from flask import Flask

from db import db
from errors import ApiError
from response import error
from routes import (
    clock,
    crop_plans,
    customers,
    delivery,
    food_safety,
    seed_lots,
    spoilage,
    standing_orders,
    surplus,
    trials,
    varieties,
)

API_PREFIX = "/grow"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        customers,
        varieties,
        trials,
        seed_lots,
        food_safety,
        crop_plans,
        standing_orders,
        delivery,
        spoilage,
        surplus,
        clock,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
