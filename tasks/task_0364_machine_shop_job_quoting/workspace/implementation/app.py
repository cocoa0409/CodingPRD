"""Machine Shop / Job Shop Quoting & Production API — entry point.

In-memory only. NO seeding of any entity at startup. The store starts empty
on every boot; tests construct all preconditions via the declared API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.rfqs import bp as rfqs_bp
from routes.quotes import bp as quotes_bp
from routes.work_orders import bp as work_orders_bp
from routes.material import bp as material_bp
from routes.machine_slots import bp as machine_slots_bp
from routes.inspections import bp as inspections_bp
from routes.shipments import bp as shipments_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(rfqs_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(material_bp)
    app.register_blueprint(machine_slots_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(shipments_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Body-parse / malformed-request errors surface as 400 by default;
        # map generic client errors to the request-validation error.
        if e.code and 400 <= e.code < 500:
            return error_response("ERR_INVALID_REQUEST", 422, e.description or "Invalid request")
        return error_response("ERR_INVALID_REQUEST", 422, "Invalid request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
