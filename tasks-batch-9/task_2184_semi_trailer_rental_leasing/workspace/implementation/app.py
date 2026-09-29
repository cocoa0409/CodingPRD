"""Semi-Trailer Rental & Leasing API.

Entry point.  Storage is in-memory only and starts EMPTY on every boot --
no entity is seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes.agreements import bp as agreements_bp
from routes.parties import bp as parties_bp
from routes.reference import bp as reference_bp
from routes.relocations import bp as relocations_bp
from routes.shop import bp as shop_bp
from routes.units import bp as units_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(shop_bp)
    app.register_blueprint(relocations_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope.error("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return envelope.error("ERR_NOT_FOUND", "Method not allowed", 405)
        if exc.code in (400, 415):
            return envelope.error("ERR_INVALID_REQUEST", "Malformed request", 422)
        return envelope.error("ERR_INVALID_REQUEST", exc.description or "Request failed",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return envelope.error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
