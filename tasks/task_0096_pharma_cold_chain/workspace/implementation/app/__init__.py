"""Flask app factory for the Pharma Cold-Chain API."""
from __future__ import annotations

from flask import Flask, jsonify

from .errors import register_error_handlers
from .routes import register_all_routes
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False  # type: ignore[attr-defined]

    reset_store()
    register_error_handlers(app)
    register_all_routes(app)

    @app.route("/__test__/reset", methods=["POST"])
    def __test_reset():
        reset_store()
        return jsonify({"ok": True}), 200

    return app


__all__ = ["create_app"]
