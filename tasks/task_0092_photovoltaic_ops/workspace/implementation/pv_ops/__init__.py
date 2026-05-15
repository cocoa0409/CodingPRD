"""Photovoltaic ops API package."""
from flask import Flask, jsonify

from pv_ops.errors import APIError, register_error_handlers
from pv_ops.routes import register_routes
from pv_ops.store import Store


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROVIDE_AUTOMATIC_OPTIONS"] = True

    # Single global in-memory store shared by all handlers.
    app.extensions["store"] = Store()

    register_error_handlers(app)
    register_routes(app)

    # Test-only extension hook: wipe in-memory state between test cases.
    # Parallels PRD §3.2's administrative clock/event hooks; not a business
    # operation. Conftest tolerates 404 if absent, but we expose it so the
    # benchmark's shared catalog state cannot leak across tests.
    @app.route("/__test__/reset", methods=["POST"])
    def _test_reset():  # pragma: no cover - exercised via integration tests
        app.extensions["store"] = Store()
        return jsonify({"ok": True}), 200

    return app


__all__ = ["create_app", "APIError"]
