"""Product Sampling & Seeding API — Flask entrypoint.

Storage is in-memory only (see db.py): every boot starts from a completely
empty store with no seeded, preloaded or hardcoded entity data.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (campaigns, clock_admin, diversion_cases, enrollments,
                    fulfillment, kit_lines, lift_analyses, panelists,
                    purchase_matches, retailers, review_submissions,
                    sample_shipments, syndication_records)

BLUEPRINTS = (
    campaigns.bp,
    kit_lines.bp,
    fulfillment.bp,
    panelists.bp,
    enrollments.bp,
    sample_shipments.bp,
    review_submissions.bp,
    retailers.bp,
    syndication_records.bp,
    diversion_cases.bp,
    purchase_matches.bp,
    lift_analyses.bp,
    clock_admin.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.failure(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return response.failure("ERR_NOT_FOUND", "The requested path does not exist",
                                    404)
        if exc.code == 405:
            return response.failure("ERR_METHOD_NOT_ALLOWED",
                                    "The method is not allowed for this path", 405)
        if exc.code == 400:
            return response.failure("ERR_INVALID_REQUEST",
                                    "The request payload is invalid", 400)
        return response.failure("ERR_INTERNAL", exc.description or "Unexpected error",
                                exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return response.failure("ERR_INTERNAL", "%s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
