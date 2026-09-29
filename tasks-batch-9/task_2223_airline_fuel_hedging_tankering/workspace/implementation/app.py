"""Airline Fuel Hedging & Tankering API — Flask application entrypoint.

Storage is entirely in-memory (plain dicts in db.py) and starts EMPTY on every
boot: nothing is ever seeded, preloaded or persisted to disk.
"""

import os

from flask import Flask

from errors import ApiError
from middleware import init_request_state
from response import error_body
from routes import (clock, counterparties, directives, exceptions, forecasts,
                    instruments, legs, mtm, policies, postings, programs,
                    stations)

BLUEPRINTS = (
    policies.bp,
    counterparties.bp,
    stations.bp,
    forecasts.bp,
    programs.bp,
    instruments.bp,
    postings.bp,
    mtm.bp,
    legs.bp,
    directives.bp,
    exceptions.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        init_request_state()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_body("ERR_INVALID_REQUEST", "The requested route does not exist."), 404

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error_body("ERR_INVALID_REQUEST",
                          "The HTTP method is not allowed for this route."), 405

    @app.errorhandler(400)
    def _bad_request(_exc):
        return error_body("ERR_INVALID_REQUEST", "The request could not be parsed."), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.message), exc.http_status
        app.logger.exception("unhandled error: %s", exc)
        return error_body("ERR_INVALID_REQUEST", "Internal server error: %s" % exc), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
