"""Correspondent Banking Due Diligence API — Flask application entry point.

Storage is in-memory only, so every process launch starts from an empty world.
No entity data is ever seeded: tests construct everything through the endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

import routes_alerts
import routes_clock
import routes_closure
import routes_jurisdictions
import routes_media
import routes_monitoring
import routes_nested
import routes_owners
import routes_payments
import routes_questionnaires
import routes_refresh
import routes_respondents
import routes_rfis

BLUEPRINTS = (
    routes_jurisdictions.bp,
    routes_respondents.bp,
    routes_owners.bp,
    routes_questionnaires.bp,
    routes_nested.bp,
    routes_monitoring.bp,
    routes_alerts.bp,
    routes_rfis.bp,
    routes_media.bp,
    routes_refresh.bp,
    routes_payments.bp,
    routes_closure.bp,
    routes_clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such resource.", 404)
        if exc.code == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed on this path.", 405)
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST_BODY",
                                  "Request body must be a JSON object.", 400)
        return response.error("ERR_INTERNAL", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return response.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
