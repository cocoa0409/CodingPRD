"""Flood Zone Determination and Map Amendment Support API.

Everything lives in memory: no database, no file cache, and no seed data --
every entity in this service is created by an API call.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
import routes_disputes
import routes_folios
import routes_notices
import routes_panels
import routes_parties
import routes_reads

API_PREFIX = "/flood-zone"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (
        routes_reads,
        routes_parties,
        routes_panels,
        routes_folios,
        routes_notices,
        routes_disputes,
    ):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def _handle_bad_request(exc):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "The request could not be parsed.")),
            400,
        )

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return (
            jsonify(
                error_body("ERR_INVALID_REQUEST", "No such endpoint on this service.")
            ),
            404,
        )

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return (
            jsonify(
                error_body(
                    "ERR_INVALID_REQUEST",
                    "That method is not allowed on this endpoint.",
                )
            ),
            405,
        )

    @app.errorhandler(415)
    def _handle_unsupported_media(exc):
        return (
            jsonify(
                error_body("ERR_INVALID_REQUEST", "The request body must be JSON.")
            ),
            400,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return _handle_api_error(exc)
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Unhandled error: %s" % exc)),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
