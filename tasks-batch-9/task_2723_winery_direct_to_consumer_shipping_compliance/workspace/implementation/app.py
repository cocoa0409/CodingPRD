"""Winery Direct-to-Consumer Shipping Compliance API.

Flask application factory and error envelope. Storage is in-memory only and
nothing is seeded: every entity comes into existence through an API call.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.carriers import bp as carriers_bp
from routes.club import bp as club_bp
from routes.consumers import bp as consumers_bp
from routes.orders import bp as orders_bp
from routes.permits import bp as permits_bp
from routes.reference import bp as reference_bp
from routes.remittances import bp as remittances_bp
from routes.shipments import bp as shipments_bp

_HTTP_ERROR_IDS = {
    400: "ERR_INVALID_REQUEST",
    401: "ERR_UNAUTHENTICATED",
    403: "ERR_UNAUTHORIZED",
    404: "ERR_NOT_FOUND",
    405: "ERR_METHOD_NOT_ALLOWED",
    415: "ERR_INVALID_REQUEST",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (reference_bp, permits_bp, carriers_bp, consumers_bp,
                      club_bp, orders_bp, shipments_bp, remittances_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        code = exc.code or 500
        error_id = _HTTP_ERROR_IDS.get(code, "ERR_INVALID_REQUEST" if code < 500
                                       else "ERR_INTERNAL")
        return response.error(error_id, exc.description or error_id, code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
