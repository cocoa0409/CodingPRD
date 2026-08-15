"""Entry point: Flask app, error handlers, route registration.

In-memory only; the store starts empty on every boot. The logical clock
defaults to exactly 2026-08-01T00:00:00Z and moves only via
POST /motion/_clock/set_current_utc.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import store
from errors import ApiError
from response import error_response, _meta
from flask import jsonify

from routes.clock import bp as clock_bp
from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.branches import bp as branches_bp
from routes.orders import bp as orders_bp
from routes.callouts import bp as callouts_bp
from routes.consignment import bp as consignment_bp
from routes.service import bp as service_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        status = e.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id,
                     "message": getattr(e, "description", str(e))},
        }
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
        }
        return jsonify(body), 500

    for bp in (clock_bp, catalog_bp, customers_bp, branches_bp, orders_bp,
               callouts_bp, consignment_bp, service_bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False, debug=False)
