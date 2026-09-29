"""Surplus Public Land Disposition API.

Flask application factory and process entry point.  All state lives in the
in-memory dicts of db.py: nothing is seeded, nothing is written to disk, and
every byte vanishes when the process exits.
"""

import os

from flask import Flask

import db
import response
from errors import ApiError
from routes import (allocations, appraisals, conveyances, declarations, env_reviews,
                    notices, offerings, offers, parcels, registries)

BLUEPRINTS = (
    registries.bp,
    parcels.bp,
    declarations.bp,
    notices.bp,
    offers.bp,
    appraisals.bp,
    env_reviews.bp,
    offerings.bp,
    conveyances.bp,
    allocations.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "No such route on this service.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "That method is not allowed on this route.", 405)

    @app.errorhandler(400)
    def handle_bad_request(_error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return handle_api_error(error)
        return response.error_response("ERR_INVALID_REQUEST", str(error), 400)

    # A fresh process starts from an empty store and the default logical clock.
    db.reset()
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
