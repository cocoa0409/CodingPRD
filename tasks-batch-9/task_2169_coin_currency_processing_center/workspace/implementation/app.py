"""Coin & Currency Processing Center API.

Entry point: registers every blueprint under the /cash-vault prefix, installs the
envelope error handlers, and serialises requests through one process-wide lock so
the in-memory store stays consistent under the harness's concurrent probes.

The store is created empty on every boot and NOTHING is ever seeded here.
"""

import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ApiError, respond_error, store_lock  # noqa: E402
from routes.bags import bp as bags_bp  # noqa: E402
from routes.claims import bp as claims_bp  # noqa: E402
from routes.coin_orders import bp as coin_orders_bp  # noqa: E402
from routes.counterfeit import bp as counterfeit_bp  # noqa: E402
from routes.customers import bp as customers_bp  # noqa: E402
from routes.fed_deposits import bp as fed_deposits_bp  # noqa: E402
from routes.sessions import bp as sessions_bp  # noqa: E402
from routes.tickets import bp as tickets_bp  # noqa: E402
from routes.vaults import bp as vaults_bp  # noqa: E402

API_PREFIX = "/cash-vault"


class SerialisingMiddleware(object):
    """Serialise request handling so concurrent writers cannot interleave."""

    def __init__(self, wsgi_app, lock):
        self.wsgi_app = wsgi_app
        self.lock = lock

    def __call__(self, environ, start_response):
        with self.lock:
            return list(self.wsgi_app(environ, start_response))


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        vaults_bp,
        customers_bp,
        tickets_bp,
        bags_bp,
        sessions_bp,
        counterfeit_bp,
        claims_bp,
        fed_deposits_bp,
        coin_orders_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return respond_error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return respond_error("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return respond_error("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return respond_error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("Unhandled error: %s", exc)
        return respond_error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    app.wsgi_app = SerialisingMiddleware(app.wsgi_app, store_lock)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
