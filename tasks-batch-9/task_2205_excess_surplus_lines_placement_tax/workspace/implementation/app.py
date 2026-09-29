"""Surplus Lines Placement Tax API — application factory and entry point.

Storage is in-memory only and NOTHING is seeded: a freshly booted process holds
zero entities of every type. The only startup state is the logical clock, which
begins at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import auth
from envelope import error_response
from errors import ApiError
from routes import (affidavits, brokers, cancellations, carriers, clock_routes,
                    eligibilities, endorsements, filing, placements, policies,
                    policy_tax, state_programs)

BLUEPRINTS = (
    clock_routes.bp,
    brokers.bp,
    state_programs.bp,
    carriers.bp,
    eligibilities.bp,
    placements.bp,
    policies.bp,
    policy_tax.bp,
    endorsements.bp,
    cancellations.bp,
    affidavits.bp,
    filing.bp,
)


def _plain_error(error_id, status, message):
    err = ApiError(error_id, message)
    err.http_status = status
    return error_response(err)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _authenticate():
        # Rungs 1 and 2 run before the path is inspected, so they apply even to
        # requests aimed at paths this API does not serve.
        auth.authenticate()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return _plain_error("ERR_NOT_FOUND", 404, "No such route.")
        if err.code == 405:
            return _plain_error("ERR_METHOD_NOT_ALLOWED", 405,
                                "Method not allowed for this route.")
        return _plain_error("ERR_INVALID_REQUEST", err.code or 400,
                            err.description or "Bad request.")

    @app.errorhandler(Exception)
    def _unexpected(err):  # pragma: no cover - defensive
        return _plain_error("ERR_INVALID_REQUEST", 500, str(err))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
