"""Freight Bid Management API — entry point, blueprint registration and the error
envelope of PRD §2.2.  Storage is in-memory only and starts empty on every boot."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import responses
import store
from errors import ApiError
from routes import (allocations, carriers, clock, contracts, events, invitations,
                    lanebids, lanes, minibids, optimization, raterecords, reviews,
                    rounds, scorecards)

BLUEPRINTS = (clock.bp, carriers.bp, reviews.bp, scorecards.bp, events.bp, lanes.bp,
              invitations.bp, rounds.bp, lanebids.bp, optimization.bp, allocations.bp,
              contracts.bp, raterecords.bp, minibids.bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        # A row mutated more than once inside a single request bumps its version once.
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return responses.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return responses.error("ERR_INVALID_REQUEST", "Unknown route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return responses.error("ERR_INVALID_REQUEST",
                               "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        return responses.error(error_id, exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return responses.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
