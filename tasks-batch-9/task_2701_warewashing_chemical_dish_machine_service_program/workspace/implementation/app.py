"""Warewashing Chemical & Dish Machine Service Program API.

A single Flask process holding every row in memory. No data is seeded,
persisted or read from disk, so every fresh boot starts completely empty
with the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g

import db
import response
from errors import ApiError

from routes.agreements import bp as agreements_bp
from routes.catalog import bp as catalog_bp
from routes.clock import bp as clock_bp
from routes.deliveries import bp as deliveries_bp
from routes.dispensers import bp as dispensers_bp
from routes.placements import bp as placements_bp
from routes.reviews import bp as reviews_bp
from routes.tickets import bp as tickets_bp
from routes.visits import bp as visits_bp

PREFIX = "/warewashing"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        clock_bp, catalog_bp, agreements_bp, placements_bp, dispensers_bp,
        tickets_bp, visits_bp, deliveries_bp, reviews_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error(
            "ERR_RESOURCE_NOT_FOUND", "The addressed resource does not exist", 404
        )

    @app.errorhandler(405)
    def _not_allowed(exc):
        return response.error(
            "ERR_RESOURCE_NOT_FOUND", "The addressed resource does not exist", 404
        )

    @app.errorhandler(400)
    def _bad_request(exc):
        return response.error(
            "ERR_INVALID_REQUEST", "The request could not be understood", 400
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return response.error("ERR_INVALID_REQUEST", str(exc), 500)

    @app.teardown_request
    def _drop_dirty_flags(exc):
        """A rejected request leaves no row flagged for a version bump."""
        dirty = getattr(g, "dirty_rows", None)
        if not dirty:
            return
        for row in dirty:
            row.pop("_dirty", None)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
