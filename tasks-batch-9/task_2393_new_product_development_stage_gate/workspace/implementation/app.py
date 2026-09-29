"""NPD Stage-Gate API — application wiring.

A fresh process holds no entities: every store in ``db`` starts empty and the
logical clock starts at ``2026-08-01T00:00:00Z``. Nothing is seeded, nothing is
written to disk, so the per-test server reboot the harness performs gives every
test a pristine system.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as R
from errors import ApiError
from routes import (business_cases, config_roots, deliverables, formulations,
                    gate_reviews, labels, launch, pilots, projects, sellin)

BLUEPRINTS = (
    config_roots.bp,
    projects.bp,
    business_cases.bp,
    deliverables.bp,
    gate_reviews.bp,
    formulations.bp,
    pilots.bp,
    labels.bp,
    sellin.bp,
    launch.bp,
)


class SerializingMiddleware:
    """One request at a time.

    Every write in this API reads and rewrites derived fields across several
    aggregates (the budget ledger, slot counts, ACV, readiness). Serialising
    requests keeps those conserved quantities exact under concurrent load
    without sprinkling locks through the route layer.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return R.error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return R.error_response("ERR_NOT_FOUND", 404,
                                    "No such route on this API.")
        if exc.code == 405:
            return R.error_response("ERR_METHOD_NOT_ALLOWED", 405,
                                    "That method is not allowed on this route.")
        if exc.code == 400:
            return R.error_response("ERR_INVALID_REQUEST", 400,
                                    "The request could not be parsed.")
        return R.error_response("ERR_INTERNAL", exc.code or 500,
                                exc.description or "Request failed.")

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return R.error_response("ERR_INTERNAL", 500, str(exc) or "Server error.")

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
