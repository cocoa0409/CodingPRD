"""Fixed-wireless rural ISP: tower, subscriber and installation API.

In-memory only: every process start begins with completely empty stores, and
nothing is ever persisted or seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import flows
import response
from errors import ApiError
from routes import field, outage, plant, rf, sales


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plant.bp)
    app.register_blueprint(rf.bp)
    app.register_blueprint(sales.bp)
    app.register_blueprint(field.bp)
    app.register_blueprint(outage.bp)

    @app.before_request
    def _settle_the_clock():
        """Lazy expiry (PRD 2.4): reservations lapse the moment the logical
        clock has passed them, evaluated at the head of every request."""
        flows.lapse_expired_holds()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message,
                                      error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if error.code == 405:
            return response.error_response("ERR_METHOD_NOT_ALLOWED",
                                           "Method not allowed.", 405)
        if error.code == 400:
            return response.error_response("ERR_VALIDATION",
                                           "The request body is not valid JSON.", 400)
        return response.error_response("ERR_INTERNAL", "Internal server error.",
                                      error.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - safety net
        return response.error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
