"""Flask app factory for the Judicial Auction Platform API."""
from __future__ import annotations

from flask import Flask

from .errors import register_error_handlers
from .routes import register_all_routes
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False  # type: ignore[attr-defined]

    reset_store()
    register_error_handlers(app)
    register_all_routes(app)

    # Test-harness reset hook. Not part of the PRD surface. Allows the
    # test runner to wipe the in-memory store and reset the logical
    # clock between tests for clean isolation.
    @app.route("/__test__/reset", methods=["POST"])
    def _test_reset():
        reset_store()
        return {"meta": {}, "response_type": "object", "data": {}}, 200

    return app


__all__ = ["create_app"]
