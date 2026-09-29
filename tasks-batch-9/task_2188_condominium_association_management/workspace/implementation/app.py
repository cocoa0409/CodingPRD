"""Condominium Association Management API -- entry point.

Storage is in-memory only and starts completely empty on every boot.  No entity
is ever seeded, preloaded or hardcoded here: every entity a client needs is
constructed through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (assessments, cases, certificates, claims, core, elements,
                        ledger_routes, meetings, planning)

    for module in (core, ledger_routes, planning, assessments, meetings, elements,
                   claims, cases, certificates):
        module.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error("ERR_VALIDATION", "Unknown route.", 404)

    @app.errorhandler(405)
    def _bad_method(exc):
        return response.error("ERR_VALIDATION", "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error("ERR_VALIDATION", "Malformed request.", 422)
        return response.error("ERR_VALIDATION", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover
        import traceback
        traceback.print_exc()
        return response.error("ERR_VALIDATION", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
