"""GLP-1 Weight-Loss Telehealth API — application entry point.

Mounted under /glp1 (SCAFFOLD api_prefix).  Storage is in-memory only and the
store is empty on every boot: nothing is seeded, preloaded or persisted.
"""

import os
import sys
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import envelope  # noqa: E402
import errors  # noqa: E402
from errors import ApiError  # noqa: E402

API_PREFIX = "/glp1"


class SerializingMiddleware:
    """Serialise request handling so multi-step mutations stay atomic.

    Conservation identities (PRD 2.10) must hold at every observable point, so
    a request is applied end to end before the next one begins.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return list(self.wsgi_app(environ, start_response))


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    from routes.directory import bp as directory_bp
    from routes.clinical import bp as clinical_bp
    from routes.prescriptions import bp as prescriptions_bp
    from routes.payer import bp as payer_bp
    from routes.fulfillment import bp as fulfillment_bp
    from routes.billing import bp as billing_bp
    from routes.surveillance import bp as surveillance_bp

    for blueprint in (directory_bp, clinical_bp, prescriptions_bp, payer_bp,
                      fulfillment_bp, billing_bp, surveillance_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return envelope.failure(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return envelope.failure("ERR_NOT_FOUND", "Unknown route.", 404)
        if exc.code == 405:
            return envelope.failure("ERR_METHOD_NOT_ALLOWED",
                                    "Method not allowed for this route.", 405)
        return envelope.failure(errors.ERR_VALIDATION,
                                exc.description or "Bad request.", exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return envelope.failure("ERR_INTERNAL", "Unexpected server error.", 500)

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
