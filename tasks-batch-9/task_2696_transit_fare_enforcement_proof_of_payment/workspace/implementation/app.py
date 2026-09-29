"""Transit Fare Enforcement & Proof of Payment API.

Entry point: blueprint registration, envelope-shaped error handling and the
foreground server.  Storage is in-memory and starts completely empty on every
boot -- no entity is seeded, preloaded or hardcoded here or anywhere else.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_appeals
import routes_citations
import routes_deployments
import routes_reports
import routes_settlement
import routes_zones


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_zones.bp)
    app.register_blueprint(routes_deployments.bp)
    app.register_blueprint(routes_citations.bp)
    app.register_blueprint(routes_appeals.bp)
    app.register_blueprint(routes_settlement.bp)
    app.register_blueprint(routes_reports.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_INVALID_REQUEST", "No such route.", 404)
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST",
                                 "Method not allowed for this route.", 405)
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The request could not be parsed.", 400)
        return respond_error("ERR_INVALID_REQUEST", exc.description or "Request rejected.",
                             exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return respond_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False, debug=False)
