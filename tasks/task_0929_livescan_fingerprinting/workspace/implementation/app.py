import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from authz import authenticate, authorize
from envelope import error_response
from errors import ApiError
from store import db

BLUEPRINT_MODULES = (
    "routes.agencies",
    "routes.oris",
    "routes.service_types",
    "routes.sites",
    "routes.devices",
    "routes.assignments",
    "routes.applicants",
    "routes.appointments",
    "routes.cards",
    "routes.submissions",
    "routes.chr",
    "routes.determinations",
    "routes.rapback",
    "routes.fees",
    "routes.invoices",
    "routes.ops",
)


class _Serialized:
    """Every request is applied atomically: a multi-row operation either commits
    all of its writes or none of them is observed part-way by another caller."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    import importlib

    for name in BLUEPRINT_MODULES:
        module = importlib.import_module(name)
        app.register_blueprint(module.bp)

    @app.before_request
    def _before():
        db.begin_request()
        authenticate()
        authorize()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_REFERENCE_NOT_FOUND", "resource not found")
        return error_response("ERR_INVALID_REQUEST", exc.description or "invalid request")

    app.wsgi_app = _Serialized(app.wsgi_app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
