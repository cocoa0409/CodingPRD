"""Production Music Library Licensing service — Flask application factory.

Storage is in-memory only (plain Python dicts in db.py).  Nothing is seeded,
preloaded or persisted, so every fresh process starts with an empty store and a
logical clock pinned at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    agreements,
    blanket,
    clock,
    composers,
    compositions,
    cue_sheets,
    infringement,
    licensees,
    licenses,
    royalty,
    search_profile,
    sync_requests,
    tiers,
    usage_reports,
)

BLUEPRINTS = (
    clock.bp,
    composers.bp,
    agreements.bp,
    compositions.bp,
    search_profile.bp,
    tiers.bp,
    licensees.bp,
    sync_requests.bp,
    licenses.bp,
    blanket.bp,
    usage_reports.bp,
    cue_sheets.bp,
    infringement.bp,
    royalty.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_VALIDATION", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error_response("ERR_VALIDATION", "Method not allowed on this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "Malformed request.", 422)
        return error_response("ERR_VALIDATION", exc.description or "Request refused.", exc.code)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_VALIDATION", "Unhandled server error: %s" % (exc,), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=False,
        use_reloader=False,
    )
