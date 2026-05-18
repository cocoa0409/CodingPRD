"""Flask application factory for the Real Estate Closing & Escrow API."""
from __future__ import annotations

from flask import Flask, jsonify

from app import store
from app.errors import register_error_handlers
from app.routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    register_error_handlers(app)
    register_routes(app)

    @app.route("/__test__/reset", methods=["POST"])
    def __test_reset():
        store.reset_all()
        return jsonify({"ok": True}), 200

    return app
