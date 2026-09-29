"""Senior Living Dining Program & Therapeutic Diets API.

Flask application factory and process entry point.  All state lives in
process memory (see db.py); nothing is seeded, persisted or cached on disk,
so every fresh boot starts from a completely empty store.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import (
    clock_ctl, communities, diet_orders, menus, reconciliations, reservations,
    residents, reviews, tickets, venues,
)

BLUEPRINTS = (
    communities.bp,
    venues.bp,
    residents.bp,
    diet_orders.bp,
    reservations.bp,
    menus.bp,
    tickets.bp,
    reconciliations.bp,
    reviews.bp,
    clock_ctl.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_INVALID_REQUEST", "The requested path does not exist", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error("ERR_INVALID_REQUEST", "The method is not allowed for this path", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", exc.description or "Malformed request", 400)
        return error(
            "ERR_INVALID_REQUEST",
            exc.description or "Request could not be processed",
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
