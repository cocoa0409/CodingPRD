"""Consulting Engagement Scoping & Change Control API.

Flask application factory.  Storage is process-local, in-memory and starts
completely empty on every boot: nothing is seeded or preloaded.
"""

import os

from flask import Flask, g, request

from errors import ApiError
from middleware import authenticate
from response import error
from routes.change_requests import bp as change_requests_bp
from routes.deliverables import bp as deliverables_bp
from routes.engagements import bp as engagements_bp
from routes.masterdata import bp as masterdata_bp
from routes.opportunities import bp as opportunities_bp
from routes.quality import bp as quality_bp
from routes.sows import bp as sows_bp
from routes.time_entries import bp as time_entries_bp

API_PREFIX = "/consulting"

BLUEPRINTS = (
    masterdata_bp,
    opportunities_bp,
    deliverables_bp,
    sows_bp,
    engagements_bp,
    time_entries_bp,
    change_requests_bp,
    quality_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.before_request
    def _before():
        g.touched_rows = set()
        if request.method == "OPTIONS":
            return None
        authenticate()
        return None

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.status)
        app.logger.exception("unhandled error")
        return error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
