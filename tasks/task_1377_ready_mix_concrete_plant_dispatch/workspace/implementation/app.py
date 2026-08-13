"""Ready Mix Dispatch API — Flask entry point."""

import os
import traceback

from flask import Flask

import errors
import response
from routes.catalog import bp as catalog_bp
from routes.invoices import bp as invoices_bp
from routes.loads import bp as loads_bp
from routes.orders import bp as orders_bp
from routes.qc import bp as qc_bp
from routes.trucks import bp as trucks_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (catalog_bp, trucks_bp, orders_bp, loads_bp, qc_bp, invoices_bp):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return response.error_response("ERR_VALIDATION", 400, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_exception(e):
        traceback.print_exc()
        return response.error_response("ERR_VALIDATION", 400, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
