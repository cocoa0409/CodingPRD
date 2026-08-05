"""Hospital-At-Home Program API.

Flask entry point: blueprint registration, request lifecycle hooks and the
error envelope. The store starts completely empty on every boot -- nothing is
seeded, preloaded or hardcoded here or anywhere else.
"""

import os

from flask import Flask, jsonify

import envelope
import store
from errors import ApiError
from routes import (
    beds,
    claims,
    clock_routes,
    deliveries,
    device_kits,
    episodes,
    escalations,
    meal_plans,
    monitoring,
    patients,
    referrals,
    visits,
)

BLUEPRINTS = (
    clock_routes.bp,
    patients.bp,
    referrals.bp,
    episodes.bp,
    visits.bp,
    device_kits.bp,
    monitoring.bp,
    deliveries.bp,
    meal_plans.bp,
    escalations.bp,
    beds.bp,
    claims.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _open_request():
        store.begin_request()
        store.snapshot_derived()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        body = envelope.error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        body = envelope.error_body(
            "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist."
        )
        return jsonify(body), 404

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        body = envelope.error_body(
            "ERR_RESOURCE_NOT_FOUND", "The requested method is not available on this resource."
        )
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return _api_error(exc)
        body = envelope.error_body("ERR_VALIDATION", "The request could not be processed.")
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
