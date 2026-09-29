"""Commercial Laundry Equipment Manufacturing API (Flask, in-memory store).

Every boot starts from an empty store and a logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, ApiError
from routes import (assembly_stations, build_orders, clock, distributors,
                    dossiers, machine_models, quotes, rebate_programs,
                    service_parts, technicians, warranty_claims)

MODULES = (machine_models, rebate_programs, dossiers, service_parts,
           assembly_stations, technicians, build_orders, distributors, quotes,
           warranty_claims, clock)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in MODULES:
        module.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        # An unknown path or an unsupported method is a client mistake; the
        # catalogue has no dedicated identifier, so report it as invalid.
        status = exc.code or 500
        if status == 404:
            return response.error(ERR_INVALID_REQUEST,
                                  "No such endpoint on this API.", 404)
        if status == 405:
            return response.error(ERR_INVALID_REQUEST,
                                  "That method is not allowed on this path.", 405)
        if status == 401:
            return response.error(ERR_UNAUTHENTICATED,
                                  "Authentication headers are required.", 401)
        return response.error(ERR_INVALID_REQUEST,
                              exc.description or "The request could not be served.",
                              status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error(ERR_INVALID_REQUEST,
                              "Unexpected server condition: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
