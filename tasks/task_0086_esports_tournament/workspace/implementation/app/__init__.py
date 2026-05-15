"""Flask app factory."""
from __future__ import annotations

from flask import Flask

from .errors import ApiError, register_error_handlers
from .routes import register_all_routes
from .store import reset_store


def create_app() -> Flask:
    app = Flask(__name__)
    # Make Flask preserve raw JSON dict ordering instead of mucking with key order.
    app.json.sort_keys = False  # type: ignore[attr-defined]

    # Initialise / reset the in-memory store on construction.
    reset_store()

    register_error_handlers(app)
    register_all_routes(app)

    return app


__all__ = ["create_app", "ApiError"]
