"""Appraisal review and reconsideration-of-value desk API.

Storage is in-memory only and starts completely empty on every boot: no
entity is seeded, preloaded or hardcoded anywhere in this process.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.appraisals import bp as appraisals_bp
from routes.desk_reviews import bp as desk_reviews_bp
from routes.disputes import bp as disputes_bp
from routes.escalation_orders import bp as escalation_orders_bp
from routes.reference import bp as reference_bp
from routes.rov import bp as rov_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except AttributeError:
        pass

    app.register_blueprint(reference_bp)
    app.register_blueprint(appraisals_bp)
    app.register_blueprint(desk_reviews_bp)
    app.register_blueprint(escalation_orders_bp)
    app.register_blueprint(rov_bp)
    app.register_blueprint(disputes_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The requested route does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Bad request", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
