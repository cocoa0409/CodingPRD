"""Brick & Masonry Unit Manufacturing API — Flask entry point.

The in-memory store starts EMPTY on every boot: no entity is seeded, preloaded
or hardcoded anywhere in this process.
"""

import os
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import blends, clock, fired_lots, formulations, kiln_runs, orders
from routes import plants, production_runs, sample_panels


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        plants,
        formulations,
        production_runs,
        kiln_runs,
        fired_lots,
        orders,
        blends,
        sample_panels,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Request rejected.")),
            status,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return jsonify(error_body("ERR_INVALID_REQUEST", "Unhandled server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
