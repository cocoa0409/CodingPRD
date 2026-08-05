"""Community Health Worker & SDOH Program API — application entry point.

The store starts empty on every boot: no entity is seeded, preloaded or
hardcoded anywhere in this process.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_VALIDATION
import routes_billing
import routes_config
import routes_encounters
import routes_goals
import routes_ops
import routes_referrals
import routes_resources
import routes_screening
import routes_visits


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_config.bp)
    app.register_blueprint(routes_screening.bp)
    app.register_blueprint(routes_resources.bp)
    app.register_blueprint(routes_referrals.bp)
    app.register_blueprint(routes_visits.bp)
    app.register_blueprint(routes_goals.bp)
    app.register_blueprint(routes_encounters.bp)
    app.register_blueprint(routes_billing.bp)
    app.register_blueprint(routes_ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            return envelope.error(ERR_RESOURCE_NOT_FOUND, "Resource not found", 404)
        if status == 400:
            return envelope.error(ERR_VALIDATION, "Malformed request", 400)
        return envelope.error(ERR_VALIDATION, exc.description or "Request failed", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):     # pragma: no cover - defensive
        return envelope.error(ERR_VALIDATION, "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
