"""Consumer Health Data Compliance API -- Flask entrypoint.

All state lives in process memory (see db.py) and starts empty on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, ERROR_STATUS
from routes import (assessments, breach, clock_routes, consent, consumer_requests,
                    consumers, deletion_tasks, elements, geofence, mappings,
                    policies, products, purposes, security, vendors)

BLUEPRINTS = (
    clock_routes.bp,
    products.bp,
    assessments.bp,
    elements.bp,
    purposes.bp,
    mappings.bp,
    consumers.bp,
    consent.bp,
    policies.bp,
    consumer_requests.bp,
    deletion_tasks.bp,
    vendors.bp,
    geofence.zones_bp,
    geofence.campaigns_bp,
    breach.bp,
    security.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_RESOURCE_NOT_FOUND",
                                  "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error("ERR_RESOURCE_NOT_FOUND",
                                  "The requested resource does not exist.", 404)
        if exc.code in (400, 415):
            return response.error("ERR_INVALID_REQUEST",
                                  "The request could not be understood.", 400)
        return response.error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        status = ERROR_STATUS.get("ERR_INVALID_REQUEST", 400)
        return response.error("ERR_INVALID_REQUEST", str(exc) or "Request failed.", status)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
