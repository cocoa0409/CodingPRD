"""Festival Talent Buying & Radius Administration API.

Flask application factory plus the __main__ launcher used by start.sh.
Storage is in-memory only and is EMPTY on every boot: nothing is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import respond_error

API_PREFIX = "/festival-ops"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes.advance_packets import bp as advance_packets_bp
    from routes.announcement_waves import bp as announcement_waves_bp
    from routes.artists import bp as artists_bp
    from routes.bookings import bp as bookings_bp
    from routes.competing_performances import bp as competing_performances_bp
    from routes.festivals import bp as festivals_bp
    from routes.offers import bp as offers_bp
    from routes.payment_installments import bp as payment_installments_bp
    from routes.radius_clauses import bp as radius_clauses_bp

    for blueprint in (
        festivals_bp,
        artists_bp,
        offers_bp,
        radius_clauses_bp,
        competing_performances_bp,
        bookings_bp,
        advance_packets_bp,
        payment_installments_bp,
        announcement_waves_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_NOT_FOUND", "no such resource", 404)
        if exc.code == 405:
            return respond_error(
                "ERR_METHOD_NOT_ALLOWED", "method not allowed for this path", 405
            )
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST", "malformed request", 422)
        return respond_error(
            "ERR_INVALID_REQUEST", exc.description or "request failed", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive only
        return respond_error("ERR_INTERNAL", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
