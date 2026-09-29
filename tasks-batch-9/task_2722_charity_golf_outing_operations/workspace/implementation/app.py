"""Charity Golf Outing Operations API — Flask entry point."""

import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import (allocations, assets, clock, contests, contracts, items,
                    outings, players, receipts, registrations, teams, tiers)

BLUEPRINTS = (clock, outings, contracts, tiers, registrations, players, teams,
              assets, allocations, contests, items, receipts)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in BLUEPRINTS:
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "No such route.", 404))

    @app.errorhandler(405)
    def _not_allowed(_err):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", "Method not allowed.", 405))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(
            ApiError("ERR_INTERNAL", "%s: %s" % (type(err).__name__, err), 500))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
