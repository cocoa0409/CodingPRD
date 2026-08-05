"""Unclaimed-Property Recovery & Compliance API — entry point."""
import os
from flask import Flask

from common import ApiError, err_response
import routes_entities
import routes_property
import routes_report
import routes_claim
import routes_audit


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response("ERR_INVALID_REQUEST", 400, "Unknown route.")

    @app.errorhandler(405)
    def handle_405(e):
        return err_response("ERR_INVALID_REQUEST", 400, "Method not allowed.")

    @app.errorhandler(400)
    def handle_400(e):
        return err_response("ERR_INVALID_REQUEST", 400, "Bad request.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err_response(e.error_id, e.http_status, e.message)
        return err_response("ERR_INVALID_REQUEST", 400, f"Unexpected error: {e}")

    routes_entities.register(app)
    routes_property.register(app)
    routes_report.register(app)
    routes_claim.register(app)
    routes_audit.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
