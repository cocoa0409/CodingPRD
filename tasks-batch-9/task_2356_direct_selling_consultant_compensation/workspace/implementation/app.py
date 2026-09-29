"""Direct Selling Consultant Compensation API — Flask application entry point."""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes.buybacks import bp as buybacks_bp
from routes.compliance import bp as compliance_bp
from routes.config import bp as config_bp
from routes.consultants import bp as consultants_bp
from routes.disclosures import bp as disclosures_bp
from routes.enrollment import bp as enrollment_bp
from routes.orders import bp as orders_bp
from routes.periods import bp as periods_bp
from routes.runs import bp as runs_bp

API_PREFIX = "/direct-selling"

BLUEPRINTS = (
    config_bp,
    enrollment_bp,
    consultants_bp,
    orders_bp,
    periods_bp,
    runs_bp,
    buybacks_bp,
    compliance_bp,
    disclosures_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return (
                jsonify(error_body("ERR_VALIDATION", "The requested route does not exist.")),
                404,
            )
        if exc.code == 405:
            return (
                jsonify(
                    error_body("ERR_VALIDATION", "The method is not allowed for this route.")
                ),
                405,
            )
        if exc.code in (400, 415):
            return (
                jsonify(error_body("ERR_VALIDATION", "The request shape is invalid.")),
                400,
            )
        return (
            jsonify(error_body("ERR_VALIDATION", exc.description or "Request failed.")),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return (
            jsonify(error_body("ERR_VALIDATION", "Unexpected server error: %s" % exc)),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
