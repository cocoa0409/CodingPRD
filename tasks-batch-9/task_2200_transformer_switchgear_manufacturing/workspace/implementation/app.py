"""Transformer & Switchgear Manufacturing API.

Multi-root REST service: twenty-one sibling resource families plus the
administrative clock family, all mounted at the absolute paths of PRD section 4
(there is no common API prefix). All state lives in process memory; nothing is
seeded at startup beyond the logical clock's fixed default instant.
"""
import os

from flask import Flask, jsonify

import clock
import envelope
import store
from errors import ApiError

MODULES = (
    "routes_orders",
    "routes_drawings",
    "routes_escalation",
    "routes_suppliers",
    "routes_allocations",
    "routes_tests",
    "routes_witness",
    "routes_reports",
    "routes_shipment",
    "routes_commissioning",
    "routes_warranty",
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    store.reset()
    clock.reset()

    for name in MODULES:
        module = __import__(name)
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return envelope.error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return envelope.error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error_response(exc.error_id, exc.message, exc.http_status)
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            return envelope.error_response("ERR_REQUEST_INVALID", str(exc), code)
        app.logger.exception("unhandled error")
        return envelope.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
