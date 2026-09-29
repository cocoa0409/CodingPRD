"""Renewable Diesel Plant & Feedstock Sourcing API.

In-memory only: every dict in `store` lives and dies with the process. Nothing
is seeded at startup; all state is built through the declared endpoints.
"""
import os

from flask import Flask, g

import response
from errors import ERR_INVALID_REQUEST, ApiError
from routes import (
    batches,
    clock,
    credits,
    hedges,
    hydrogen,
    lots,
    pathways,
    runs,
    suppliers,
    units,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (suppliers, lots, units, hydrogen, runs, batches,
                   pathways, credits, hedges, clock):
        app.register_blueprint(module.bp)

    @app.before_request
    def _reset_touched_rows():
        g._touched_rows = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return response.error(ERR_INVALID_REQUEST, "Malformed request body.", 422)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error(ERR_INVALID_REQUEST, "No such endpoint.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return response.error(ERR_INVALID_REQUEST,
                              "Method not allowed on this endpoint.", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
