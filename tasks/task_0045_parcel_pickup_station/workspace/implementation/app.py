"""Flask app entry point for the Parcel Pickup Station API."""
import os
import traceback
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response
from routes.system import bp as system_bp
from routes.stations import bp as stations_bp
from routes.parcels import bp as parcels_bp
from routes.returns import bp as returns_bp
from routes.billing import bp as billing_bp
from routes.quality import bp as quality_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(system_bp)
    app.register_blueprint(stations_bp)
    app.register_blueprint(parcels_bp)
    app.register_blueprint(returns_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(quality_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "Resource not found",
                              404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_VALIDATION",
                              "Method not allowed",
                              405)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        return error_response("ERR_VALIDATION",
                              e.description if hasattr(e, "description") else str(e),
                              e.code if hasattr(e, "code") and e.code else 500)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        traceback.print_exc()
        return error_response("ERR_VALIDATION",
                              f"Internal error: {type(e).__name__}: {e}",
                              500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
