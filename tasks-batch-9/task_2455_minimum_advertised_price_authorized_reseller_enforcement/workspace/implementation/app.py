"""MAP Authorized Reseller Enforcement API — Flask application entry point.

Storage is entirely in process memory (see store.py); nothing is persisted and
no entity is ever seeded, so relaunching this process wipes every byte of state.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

from envelope import error_body  # noqa: E402
from errors import ApiError  # noqa: E402
from routes import (  # noqa: E402
    agreements, chargebacks, distributors, exceptions, notices, observations, policies,
    products, resellers, serial_units, sweeps, test_purchases, violations,
)

BLUEPRINTS = (
    policies.bp,
    products.bp,
    distributors.bp,
    resellers.bp,
    agreements.bp,
    observations.bp,
    violations.bp,
    notices.bp,
    exceptions.bp,
    serial_units.bp,
    test_purchases.bp,
    chargebacks.bp,
    sweeps.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return jsonify(error_body("ERR_VALIDATION", "The requested resource does not exist.")), 404
        if status == 405:
            return jsonify(error_body("ERR_VALIDATION", "The method is not allowed on this path.")), 405
        if status == 400:
            return jsonify(error_body("ERR_VALIDATION", "The request could not be parsed.")), 400
        return jsonify(error_body("ERR_VALIDATION", exc.description or "Request failed.")), status

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return jsonify(error_body("ERR_VALIDATION", "Unexpected server error: %s" % exc)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
