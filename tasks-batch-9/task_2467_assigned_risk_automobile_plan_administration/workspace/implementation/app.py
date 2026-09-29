"""Assigned Risk Automobile Plan API — Flask application factory and entrypoint.

Storage is in-memory only and starts completely empty on every boot; no entity is
seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import store
from domain import mature_non_renewals
from envelope import error_body
from errors import ApiError

from routes.applicants import bp as applicants_bp
from routes.applications import bp as applications_bp
from routes.assignments import bp as assignments_bp
from routes.carriers import bp as carriers_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.complaints import bp as complaints_bp
from routes.periods import bp as periods_bp
from routes.policies import bp as policies_bp
from routes.producers import bp as producers_bp
from routes.reconciliations import bp as reconciliations_bp

BLUEPRINTS = (
    carriers_bp,
    producers_bp,
    applicants_bp,
    applications_bp,
    periods_bp,
    assignments_bp,
    policies_bp,
    claims_bp,
    complaints_bp,
    reconciliations_bp,
    clock_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialise_and_age():
        store.lock.acquire()
        g._plan_lock_held = True
        # PRD Section 2.12: a served non-renewal matures with the clock and is
        # observed on the next read.
        mature_non_renewals()

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_plan_lock_held", False):
            g._plan_lock_held = False
            try:
                store.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_NOT_FOUND", "Resource not found.")), 404
        if exc.code == 405:
            return (
                jsonify(
                    error_body(
                        "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path."
                    )
                ),
                405,
            )
        if exc.code == 400:
            return (
                jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request.")),
                422,
            )
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description)), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return (
            jsonify(error_body("ERR_INTERNAL", "Unexpected server error: %s" % exc)),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
