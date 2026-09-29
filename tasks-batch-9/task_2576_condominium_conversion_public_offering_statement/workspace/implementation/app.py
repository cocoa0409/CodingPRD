"""Condominium Conversion Offering API.

The application factory wires the ordered-validation pipeline, the response
envelope and one blueprint per domain area.  All state lives in plain
process-memory dictionaries in store.py: nothing is seeded at boot, nothing is
written to disk, and nothing is fetched from the network.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError
from routes import (agreements, batches, clock_routes, declaration, engineering,
                    financial, pos, projects, tenants, units, warranty)

BLUEPRINTS = (
    clock_routes.bp,
    projects.bp,
    engineering.bp,
    declaration.bp,
    units.bp,
    pos.bp,
    tenants.bp,
    financial.bp,
    batches.bp,
    agreements.bp,
    warranty.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        # One version bump per record per request, however many hops touch it.
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return envelope.error_response(error.error_id, error.message,
                                       error.http_status)

    @app.errorhandler(404)
    def _not_found(_error):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "No such endpoint on this API.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return envelope.error_response(
            "ERR_INVALID_REQUEST",
            "That method is not allowed on this endpoint.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        return envelope.error_response(
            "ERR_INVALID_REQUEST", error.description or "Malformed request.",
            error.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(error):  # pragma: no cover - defensive
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "Unhandled server error: %s" % (error,),
            500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
