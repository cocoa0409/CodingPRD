"""Convenience-store foodservice program API (Flask, in-memory).

The store starts empty on every boot: nothing is seeded, preloaded or
hardcoded, and every entity is created through the declared API surface.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_batches
import routes_config
import routes_kitchen
import routes_loyalty
import routes_orders
import routes_plans
import routes_safety
from apihttp import _meta, error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_loyalty.bp)
    app.register_blueprint(routes_plans.bp)
    app.register_blueprint(routes_batches.bp)
    app.register_blueprint(routes_safety.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_kitchen.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": err.description or "The request could not be processed.",
            },
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST",
                "message": "Unexpected server error: %s" % err,
            },
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False)
