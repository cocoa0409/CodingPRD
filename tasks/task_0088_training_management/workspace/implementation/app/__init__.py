"""Flask app factory for the Training Management API."""
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

    return app


__all__ = ["create_app"]
